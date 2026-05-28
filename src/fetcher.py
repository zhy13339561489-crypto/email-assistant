import imaplib
import email
import email.message
from email.header import decode_header
from datetime import datetime, date

from loguru import logger

from .models import EmailData


class EmailFetcher:
    NETEASE_IMAP_HOSTS = (
        "imap.163.com",
        "imap.126.com",
        "imap.yeah.net",
        "imap.188.com",
        "imap.vip.163.com",
        "imap.vip.126.com",
    )

    def __init__(self, address: str, imap_server: str, imap_port: int,
                 password: str, use_ssl: bool = True):
        self.address = address
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.password = password
        self.use_ssl = use_ssl
        self.conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None

    def connect(self) -> None:
        logger.info(f"连接邮箱 {self.imap_server}...")
        if self.use_ssl:
            self.conn = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
        else:
            self.conn = imaplib.IMAP4(self.imap_server, self.imap_port)
        self.conn.login(self.address, self.password)
        self._send_imap_id_if_needed()
        logger.info("邮箱连接成功")

    def disconnect(self) -> None:
        if self.conn:
            try:
                self.conn.logout()
            except Exception:
                pass
            self.conn = None

    def _select_inbox(self) -> None:
        errors = []
        for name in ["INBOX", "inbox"]:
            try:
                status, data = self.conn.select(name)
                logger.debug(f"SELECT {name}: status={status}, data={data}")
                if status == "OK":
                    logger.info(f"已选择邮箱: {name}")
                    return
                else:
                    errors.append(f"{name}: {status} {data}")
                    logger.warning(f"选择 {name} 失败: {status} {data}")
            except Exception as e:
                errors.append(f"{name}: {e}")
                logger.warning(f"选择 {name} 异常: {e}")
                continue
        error_text = " | ".join(errors)
        if "Unsafe Login" in error_text:
            raise RuntimeError(
                "网易邮箱拒绝选择收件箱：Unsafe Login。程序已尝试发送 IMAP ID；"
                "如果仍失败，请确认邮箱已开启 IMAP/SMTP 服务，并使用客户端授权码而不是网页登录密码。"
            )
        raise RuntimeError("无法选择收件箱")

    def _send_imap_id_if_needed(self) -> None:
        if not self.conn:
            return
        if not self._is_netease_imap() and not self._server_supports_imap_id():
            return

        imaplib.Commands["ID"] = ("NONAUTH", "AUTH", "SELECTED")
        id_args = self._build_imap_id_args()
        try:
            status, data = self.conn._simple_command("ID", id_args)
            logger.debug(f"IMAP ID: status={status}, data={data}")
            self.conn._untagged_response(status, data, "ID")
        except Exception as e:
            logger.warning(f"发送 IMAP ID 失败，后续选择收件箱可能被服务端拒绝: {e}")

    def _is_netease_imap(self) -> bool:
        host = self.imap_server.lower()
        return host in self.NETEASE_IMAP_HOSTS or host.endswith(".163.com")

    def _server_supports_imap_id(self) -> bool:
        try:
            status, data = self.conn.capability()
        except Exception as e:
            logger.debug(f"读取 IMAP capability 失败: {e}")
            return False
        if status != "OK":
            return False

        tokens = []
        for item in data or []:
            if isinstance(item, bytes):
                tokens.extend(item.upper().split())
            else:
                tokens.extend(str(item).upper().split())
        return b"ID" in tokens or "ID" in tokens

    def _build_imap_id_args(self) -> str:
        args = (
            "name", "EmailAI",
            "version", "1.0.0",
            "vendor", "EmailAI",
            "contact", self.address,
        )
        return "(" + " ".join(self._quote_imap_string(value) for value in args) + ")"

    @staticmethod
    def _quote_imap_string(value: str) -> str:
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def fetch_unread(self) -> list[EmailData]:
        self._select_inbox()
        _, data = self.conn.search(None, "UNSEEN")
        uids = data[0].split()
        if not uids:
            logger.info("没有未读邮件")
            return []

        logger.info(f"发现 {len(uids)} 封未读邮件")
        emails = []
        for uid in uids:
            try:
                msg = self._fetch_one(uid)
                if msg:
                    emails.append(msg)
            except Exception as e:
                logger.error(f"获取邮件 {uid} 失败: {e}")
        return emails

    def fetch_by_date(self, since: date, before: date) -> list[EmailData]:
        self._select_inbox()
        since_str = since.strftime("%d-%b-%Y")
        before_str = before.strftime("%d-%b-%Y")
        _, data = self.conn.search(None, f'(SINCE "{since_str}" BEFORE "{before_str}")')
        uids = data[0].split()
        if not uids:
            return []

        emails = []
        for uid in uids:
            try:
                msg = self._fetch_one(uid)
                if msg:
                    emails.append(msg)
            except Exception as e:
                logger.error(f"获取邮件 {uid} 失败: {e}")
        return emails

    def mark_as_read(self, uid: bytes) -> None:
        self.conn.store(uid, "+FLAGS", "\\Seen")

    def _fetch_one(self, uid: bytes) -> EmailData | None:
        _, msg_data = self.conn.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = self._decode_header(msg.get("Subject", ""))
        sender = msg.get("From", "")
        sender_name, sender_addr = email.utils.parseaddr(sender)
        to = msg.get("To", "")
        date_str = msg.get("Date", "")
        date = email.utils.parsedate_to_datetime(date_str) if date_str else datetime.now()

        body = self._extract_body(msg)
        attachments = self._extract_attachment_names(msg)

        return EmailData(
            uid=uid.decode(),
            subject=subject,
            sender=sender_addr or sender,
            sender_name=sender_name or sender_addr,
            to=to,
            date=date,
            body_text=body,
            has_attachments=bool(attachments),
            attachment_names=attachments,
        )

    def _decode_header(self, header: str) -> str:
        parts = decode_header(header)
        result = []
        for part, charset in parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def _extract_body(self, msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
            # 没有纯文本，尝试 HTML
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return self._html_to_text(payload.decode(charset, errors="replace"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    return self._html_to_text(text)
                return text
        return ""

    def _html_to_text(self, html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    def _extract_attachment_names(self, msg: email.message.Message) -> list[str]:
        names = []
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    names.append(self._decode_header(filename))
        return names
