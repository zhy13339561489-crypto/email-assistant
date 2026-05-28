from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr


class SMTPReplyMailer:
    def send_reply(self, account_cfg: dict, reply: dict) -> None:
        server = account_cfg.get("smtp_server") or ""
        if not server:
            raise RuntimeError("SMTP server is not configured")

        username = account_cfg.get("smtp_username") or account_cfg.get("address") or ""
        password = account_cfg.get("smtp_password") or account_cfg.get("password") or ""
        if not username or not password:
            raise RuntimeError("SMTP username or password is not configured")

        message = EmailMessage()
        message["Subject"] = reply.get("reply_subject") or ""
        message["From"] = formataddr((account_cfg.get("from_name") or "", account_cfg.get("address") or username))
        message["To"] = reply.get("sender") or ""
        message.set_content(reply.get("reply_body") or "")

        message_id = _extract_header(reply.get("raw_headers") or "", "Message-ID")
        if message_id:
            message["In-Reply-To"] = message_id
            message["References"] = message_id

        port = int(account_cfg.get("smtp_port") or (465 if account_cfg.get("smtp_use_ssl", True) else 587))
        timeout = 30
        if account_cfg.get("smtp_use_ssl", True):
            with smtplib.SMTP_SSL(server, port, timeout=timeout) as client:
                client.login(username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(server, port, timeout=timeout) as client:
                if account_cfg.get("smtp_use_tls", False):
                    client.starttls()
                client.login(username, password)
                client.send_message(message)


def _extract_header(raw_headers: str, name: str) -> str:
    prefix = name.lower() + ":"
    for line in raw_headers.splitlines():
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""
