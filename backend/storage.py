from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import decode_header
from typing import Any

from loguru import logger

from src.models import EmailData, ProcessResult

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    pymysql = None
    DictCursor = None


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"

    def validate(self) -> None:
        missing = []
        if not self.host:
            missing.append("MYSQL_HOST 或 MYSQL_IP")
        if not self.user:
            missing.append("MYSQL_USER 或 MYSQL_USERNAME")
        if not self.password:
            missing.append("MYSQL_PASSWORD")
        if not self.database:
            missing.append("MYSQL_DATABASE 或 MYSQL_DB")
        if missing:
            raise RuntimeError("MySQL 配置不完整，请在 .env 中补充：" + "、".join(missing))


class MySQLEmailStorage:
    def __init__(self, config: MySQLConfig):
        self.config = config
        self._init_db()

    @classmethod
    def from_config(cls, config: dict) -> "MySQLEmailStorage":
        db = config.get("mysql") or {}
        host = db.get("host", "127.0.0.1")
        if host == "0.0.0.0":
            host = "127.0.0.1"
        mysql_config = MySQLConfig(
            host=host,
            port=int(db.get("port", 3306)),
            user=db.get("user", ""),
            password=db.get("password", ""),
            database=db.get("database", "email_ai"),
            charset=db.get("charset", "utf8mb4"),
        )
        mysql_config.validate()
        return cls(mysql_config)

    def _get_conn(self):
        if pymysql is None:
            raise RuntimeError("缺少 MySQL 依赖，请先运行：pip install -r requirements.txt")
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset=self.config.charset,
            cursorclass=DictCursor,
            autocommit=False,
        )

    def _get_server_conn(self):
        if pymysql is None:
            raise RuntimeError("缺少 MySQL 依赖，请先运行：pip install -r requirements.txt")
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            charset=self.config.charset,
            cursorclass=DictCursor,
            autocommit=False,
        )

    def _init_db(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS emails (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                uid VARCHAR(255) NOT NULL,
                account VARCHAR(120) NOT NULL DEFAULT '',
                sender VARCHAR(512),
                sender_name VARCHAR(512),
                subject VARCHAR(1024),
                date DATETIME,
                category VARCHAR(120),
                mailbox VARCHAR(32) NOT NULL DEFAULT 'inbox',
                confidence DOUBLE,
                category_reason TEXT,
                summary TEXT,
                recipient TEXT,
                raw_body_text MEDIUMTEXT,
                raw_headers MEDIUMTEXT,
                attachment_names TEXT,
                has_attachments TINYINT(1) DEFAULT 0,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                deleted_at DATETIME NULL,
                UNIQUE KEY idx_email_uid_account (uid, account),
                KEY idx_email_mailbox (mailbox),
                KEY idx_email_category (category),
                KEY idx_email_date (date)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS action_items (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                email_id BIGINT NOT NULL,
                action TEXT,
                deadline VARCHAR(255),
                priority VARCHAR(32) DEFAULT 'normal',
                deleted_at DATETIME NULL,
                KEY idx_action_email_id (email_id),
                CONSTRAINT fk_action_email
                    FOREIGN KEY (email_id) REFERENCES emails(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_reports (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                report_date DATE NOT NULL,
                window_start DATETIME NOT NULL,
                window_end DATETIME NOT NULL,
                email_count INT NOT NULL DEFAULT 0,
                content MEDIUMTEXT,
                generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY idx_report_window (window_start, window_end),
                KEY idx_report_date (report_date)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS email_replies (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                email_id BIGINT NOT NULL,
                needs_reply TINYINT(1) NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL DEFAULT 'not_required',
                decision_reason TEXT,
                draft_subject VARCHAR(1024),
                draft_body MEDIUMTEXT,
                reviewer_notes TEXT,
                ai_review_notes TEXT,
                ai_review_rounds INT NOT NULL DEFAULT 0,
                ai_review_passed TINYINT(1) NOT NULL DEFAULT 0,
                sent_at DATETIME NULL,
                send_error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY idx_reply_email_id (email_id),
                KEY idx_reply_status (status),
                CONSTRAINT fk_reply_email
                    FOREIGN KEY (email_id) REFERENCES emails(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """,
        ]
        conn = self._connect_database_or_create()
        with conn:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                self._ensure_email_mailbox_column(cursor)
                self._ensure_email_original_columns(cursor)
                self._ensure_logical_delete_columns(cursor)
                self._ensure_reply_review_columns(cursor)
            conn.commit()
        logger.info(f"MySQL 数据库初始化完成: {self.config.host}:{self.config.port}/{self.config.database}")

    def _ensure_email_mailbox_column(self, cursor) -> None:
        cursor.execute("SHOW COLUMNS FROM emails LIKE 'mailbox'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE emails ADD COLUMN mailbox VARCHAR(32) NOT NULL DEFAULT 'inbox' AFTER category")
            cursor.execute("CREATE INDEX idx_email_mailbox ON emails (mailbox)")
        cursor.execute(
            "UPDATE emails SET mailbox = CASE WHEN category = '垃圾邮件' THEN 'spam' ELSE 'inbox' END"
        )

    def _ensure_email_original_columns(self, cursor) -> None:
        columns = {
            "recipient": "TEXT AFTER summary",
            "raw_body_text": "MEDIUMTEXT AFTER recipient",
            "raw_headers": "MEDIUMTEXT AFTER raw_body_text",
            "attachment_names": "TEXT AFTER raw_headers",
        }
        for name, definition in columns.items():
            cursor.execute(f"SHOW COLUMNS FROM emails LIKE '{name}'")
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE emails ADD COLUMN {name} {definition}")

    def _ensure_logical_delete_columns(self, cursor) -> None:
        targets = {
            "emails": "processed_at",
            "action_items": "priority",
        }
        for table, after_column in targets.items():
            cursor.execute(f"SHOW COLUMNS FROM {table} LIKE 'deleted_at'")
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at DATETIME NULL AFTER {after_column}")

    def _ensure_reply_review_columns(self, cursor) -> None:
        columns = {
            "ai_review_notes": "TEXT AFTER reviewer_notes",
            "ai_review_rounds": "INT NOT NULL DEFAULT 0 AFTER ai_review_notes",
            "ai_review_passed": "TINYINT(1) NOT NULL DEFAULT 0 AFTER ai_review_rounds",
        }
        for name, definition in columns.items():
            cursor.execute(f"SHOW COLUMNS FROM email_replies LIKE '{name}'")
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE email_replies ADD COLUMN {name} {definition}")

    def _connect_database_or_create(self):
        try:
            return self._get_conn()
        except Exception as e:
            if not _is_unknown_database_error(e):
                raise

        logger.info(f"MySQL 数据库不存在，尝试自动创建: {self.config.database}")
        with self._get_server_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.config.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            conn.commit()
        return self._get_conn()

    def save_result(self, email_data: EmailData, result: ProcessResult, account: str = "") -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO emails
                    (uid, account, sender, sender_name, subject, date,
                     category, mailbox, confidence, category_reason, summary,
                     recipient, raw_body_text, raw_headers, attachment_names, has_attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id),
                        sender = VALUES(sender),
                        sender_name = VALUES(sender_name),
                        subject = VALUES(subject),
                        date = VALUES(date),
                        category = VALUES(category),
                        mailbox = VALUES(mailbox),
                        confidence = VALUES(confidence),
                        category_reason = VALUES(category_reason),
                        summary = VALUES(summary),
                        recipient = VALUES(recipient),
                        raw_body_text = VALUES(raw_body_text),
                        raw_headers = VALUES(raw_headers),
                        attachment_names = VALUES(attachment_names),
                        has_attachments = VALUES(has_attachments),
                        processed_at = CURRENT_TIMESTAMP
                    """,
                    (
                        email_data.uid,
                        account,
                        email_data.sender,
                        email_data.sender_name,
                        email_data.subject,
                        _to_mysql_datetime(email_data.date),
                        result.classification.category,
                        _mailbox_for_category(result.classification.category),
                        result.classification.confidence,
                        result.classification.reason,
                        result.summary,
                        email_data.to,
                        email_data.raw_body_text or email_data.body_text,
                        email_data.raw_headers,
                        json.dumps(email_data.attachment_names, ensure_ascii=False),
                        int(email_data.has_attachments),
                    ),
                )
                email_id = cursor.lastrowid
                cursor.execute(
                    "UPDATE action_items SET deleted_at = CURRENT_TIMESTAMP WHERE email_id = %s AND deleted_at IS NULL",
                    (email_id,),
                )
                for item in result.action_items:
                    cursor.execute(
                        """
                        INSERT INTO action_items (email_id, action, deadline, priority)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (email_id, item.action, item.deadline, item.priority),
                    )
            conn.commit()
            return email_id

    def has_email(self, uid: str, account: str = "") -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM emails WHERE uid = %s AND account = %s LIMIT 1",
                    (uid, account),
                )
                return cursor.fetchone() is not None

    def soft_delete_email(self, email_id: int) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE emails
                    SET deleted_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND deleted_at IS NULL
                    """,
                    (email_id,),
                )
                deleted = cursor.rowcount > 0
                cursor.execute(
                    """
                    UPDATE action_items
                    SET deleted_at = CURRENT_TIMESTAMP
                    WHERE email_id = %s AND deleted_at IS NULL
                    """,
                    (email_id,),
                )
            conn.commit()
        return deleted

    def soft_delete_action_item(self, action_id: int) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE action_items
                    SET deleted_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND deleted_at IS NULL
                    """,
                    (action_id,),
                )
                deleted = cursor.rowcount > 0
            conn.commit()
        return deleted

    def original_fields_missing(self, uid: str, account: str = "") -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT raw_body_text, raw_headers
                    FROM emails
                    WHERE uid = %s AND account = %s
                    LIMIT 1
                    """,
                    (uid, account),
                )
                row = cursor.fetchone()
        return bool(row and (not row.get("raw_body_text") or not row.get("raw_headers")))

    def update_original_fields(self, email_data: EmailData, account: str = "") -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE emails
                    SET recipient = %s,
                        raw_body_text = %s,
                        raw_headers = %s,
                        attachment_names = %s,
                        has_attachments = %s
                    WHERE uid = %s AND account = %s
                    """,
                    (
                        email_data.to,
                        email_data.raw_body_text or email_data.body_text,
                        email_data.raw_headers,
                        json.dumps(email_data.attachment_names, ensure_ascii=False),
                        int(email_data.has_attachments),
                        email_data.uid,
                        account,
                    ),
                )
                updated = cursor.rowcount
            conn.commit()
        return updated

    def save_reply_decision(
        self,
        email_id: int,
        needs_reply: bool,
        reason: str = "",
        draft_subject: str = "",
        draft_body: str = "",
        ai_review_notes: str = "",
        ai_review_rounds: int = 0,
        ai_review_passed: bool = False,
        status: str | None = None,
    ) -> int:
        reply_status = status or ("pending_review" if needs_reply else "not_required")
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO email_replies
                    (email_id, needs_reply, status, decision_reason, draft_subject, draft_body,
                     ai_review_notes, ai_review_rounds, ai_review_passed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id),
                        needs_reply = IF(status = 'sent', needs_reply, VALUES(needs_reply)),
                        status = IF(status = 'sent', status, VALUES(status)),
                        decision_reason = IF(status = 'sent', decision_reason, VALUES(decision_reason)),
                        draft_subject = IF(status = 'sent', draft_subject, VALUES(draft_subject)),
                        draft_body = IF(status = 'sent', draft_body, VALUES(draft_body)),
                        ai_review_notes = IF(status = 'sent', ai_review_notes, VALUES(ai_review_notes)),
                        ai_review_rounds = IF(status = 'sent', ai_review_rounds, VALUES(ai_review_rounds)),
                        ai_review_passed = IF(status = 'sent', ai_review_passed, VALUES(ai_review_passed)),
                        send_error = IF(status = 'sent', send_error, NULL),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        email_id,
                        int(needs_reply),
                        reply_status,
                        reason,
                        draft_subject,
                        draft_body,
                        ai_review_notes,
                        int(ai_review_rounds or 0),
                        int(ai_review_passed),
                    ),
                )
                reply_id = cursor.lastrowid
            conn.commit()
        return reply_id

    def update_reply_draft(
        self,
        reply_id: int,
        subject: str,
        body: str,
        reviewer_notes: str = "",
        ai_review_notes: str = "",
        ai_review_rounds: int = 0,
        ai_review_passed: bool = False,
        status: str = "pending_review",
    ) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE email_replies
                    SET draft_subject = %s,
                        draft_body = %s,
                        reviewer_notes = %s,
                        ai_review_notes = %s,
                        ai_review_rounds = %s,
                        ai_review_passed = %s,
                        status = %s,
                        send_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status <> 'sent'
                    """,
                    (
                        subject,
                        body,
                        reviewer_notes,
                        ai_review_notes,
                        int(ai_review_rounds or 0),
                        int(ai_review_passed),
                        status,
                        reply_id,
                    ),
                )
                updated = cursor.rowcount > 0
            conn.commit()
        return updated

    def get_reply_with_email(self, reply_id: int) -> dict | None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        r.id AS reply_id,
                        r.needs_reply AS reply_needs_reply,
                        r.status AS reply_status,
                        r.decision_reason AS reply_reason,
                        r.draft_subject AS reply_subject,
                        r.draft_body AS reply_body,
                        r.reviewer_notes AS reply_reviewer_notes,
                        r.ai_review_notes AS reply_ai_review_notes,
                        r.ai_review_rounds AS reply_ai_review_rounds,
                        r.ai_review_passed AS reply_ai_review_passed,
                        r.sent_at AS reply_sent_at,
                        r.send_error AS reply_send_error,
                        r.created_at AS reply_created_at,
                        r.updated_at AS reply_updated_at,
                        e.*
                    FROM email_replies r
                    JOIN emails e ON e.id = r.email_id
                    WHERE r.id = %s AND e.deleted_at IS NULL
                    LIMIT 1
                    """,
                    (reply_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return _normalize_reply_email(row)

    def mark_reply_sending(self, reply_id: int) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE email_replies
                    SET status = 'approved',
                        send_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status <> 'sent'
                    """,
                    (reply_id,),
                )
                updated = cursor.rowcount > 0
            conn.commit()
        return updated

    def mark_reply_sent(self, reply_id: int) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE email_replies
                    SET status = 'sent',
                        sent_at = CURRENT_TIMESTAMP,
                        send_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (reply_id,),
                )
            conn.commit()

    def mark_reply_send_failed(self, reply_id: int, error: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE email_replies
                    SET status = 'send_failed',
                        send_error = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (error[:2000], reply_id),
                )
            conn.commit()

    def get_emails_between(self, start: datetime, end: datetime) -> list[dict]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        e.*,
                        COUNT(a.id) AS action_count,
                        GROUP_CONCAT(a.action SEPARATOR ' || ') AS action_preview,
                        MAX(r.id) AS reply_id,
                        MAX(r.needs_reply) AS reply_needs_reply,
                        MAX(r.status) AS reply_status,
                        MAX(r.decision_reason) AS reply_reason,
                        MAX(r.draft_subject) AS reply_subject,
                        MAX(r.draft_body) AS reply_body,
                        MAX(r.reviewer_notes) AS reply_reviewer_notes,
                        MAX(r.ai_review_notes) AS reply_ai_review_notes,
                        MAX(r.ai_review_rounds) AS reply_ai_review_rounds,
                        MAX(r.ai_review_passed) AS reply_ai_review_passed,
                        MAX(r.sent_at) AS reply_sent_at,
                        MAX(r.send_error) AS reply_send_error
                    FROM emails e
                    LEFT JOIN action_items a ON a.email_id = e.id AND a.deleted_at IS NULL
                    LEFT JOIN email_replies r ON r.email_id = e.id
                    WHERE e.deleted_at IS NULL
                        AND e.date >= %s AND e.date < %s
                    GROUP BY e.id
                    ORDER BY e.date DESC
                    """,
                    (_to_mysql_datetime(start), _to_mysql_datetime(end)),
                )
                return [_normalize_email(row) for row in cursor.fetchall()]

    def save_daily_report(
        self,
        report_date: date,
        window_start: datetime,
        window_end: datetime,
        email_count: int,
        content: str,
    ) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO daily_reports
                    (report_date, window_start, window_end, email_count, content)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id),
                        report_date = VALUES(report_date),
                        email_count = VALUES(email_count),
                        content = VALUES(content),
                        generated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        report_date,
                        _to_mysql_datetime(window_start),
                        _to_mysql_datetime(window_end),
                        email_count,
                        content,
                    ),
                )
                report_id = cursor.lastrowid
            conn.commit()
            return report_id

    def get_latest_daily_report(self) -> dict | None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM daily_reports
                    ORDER BY window_end DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "report_date": _json_date(row.get("report_date")),
            "window_start": _json_datetime(row.get("window_start")),
            "window_end": _json_datetime(row.get("window_end")),
            "email_count": row.get("email_count") or 0,
            "content": row.get("content") or "",
            "generated_at": _json_datetime(row.get("generated_at")),
        }

    def get_dashboard(
        self,
        days: int = 30,
        category: str = "all",
        query: str = "",
        mailbox: str = "inbox",
    ) -> dict:
        days = max(1, min(int(days or 30), 365))
        category = (category or "all").strip()
        query = (query or "").strip()
        mailbox = mailbox or "inbox"
        since = datetime.now() - timedelta(days=days)

        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                emails = self._get_emails(cursor, since, category, query, mailbox)
                action_items = [] if mailbox == "spam" else self._get_action_items(cursor, since)
                categories = self._get_category_counts(cursor, since, mailbox)
                top_senders = self._get_top_senders(cursor, since, mailbox=mailbox)

        total = len(emails)
        with_actions = sum(1 for item in emails if item["action_count"] > 0)
        avg_confidence = round(sum(item["confidence"] or 0 for item in emails) / total, 3) if total else 0
        attachments = sum(1 for item in emails if item["has_attachments"])

        return {
            "meta": {
                "days": days,
                "category": category or "all",
                "query": query,
                "mailbox": mailbox,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
            "stats": {
                "total": total,
                "with_actions": with_actions,
                "avg_confidence": avg_confidence,
                "attachments": attachments,
            },
            "categories": categories,
            "top_senders": top_senders,
            "action_items": action_items,
            "emails": emails,
        }

    def get_today_emails(self) -> list[dict]:
        today = datetime.combine(date.today(), datetime.min.time())
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM emails WHERE deleted_at IS NULL AND date >= %s ORDER BY date DESC",
                    (today,),
                )
                return [_normalize_email(row) for row in cursor.fetchall()]

    def get_action_items(self, days: int = 7) -> list[dict]:
        since = datetime.now() - timedelta(days=days)
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                return self._get_action_items(cursor, since)

    def get_stats(self, days: int = 30) -> dict:
        since = datetime.now() - timedelta(days=days)
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS c FROM emails WHERE deleted_at IS NULL AND date >= %s", (since,))
                total = cursor.fetchone()["c"]
                categories = self._get_category_counts(cursor, since)
                top_senders = self._get_top_senders(cursor, since, limit=10)
        return {
            "total": total,
            "by_category": {item["category"]: item["count"] for item in categories},
            "top_senders": top_senders,
        }

    def _get_emails(
        self,
        cursor,
        since: datetime,
        category: str,
        query: str,
        mailbox: str = "inbox",
    ) -> list[dict]:
        filters = ["e.deleted_at IS NULL", "e.date >= %s"]
        params: list[Any] = [since]
        if mailbox == "spam":
            filters.append("e.mailbox = %s")
            params.append("spam")
        else:
            filters.append("e.mailbox = %s")
            params.append("inbox")

        if category and category != "all" and mailbox != "spam":
            filters.append("e.category = %s")
            params.append(category)
        if query:
            like = f"%{query}%"
            filters.append(
                "(e.subject LIKE %s OR e.summary LIKE %s OR e.sender LIKE %s OR e.sender_name LIKE %s "
                "OR e.recipient LIKE %s OR e.raw_body_text LIKE %s OR e.raw_headers LIKE %s)"
            )
            params.extend([like, like, like, like, like, like, like])

        cursor.execute(
            f"""
            SELECT
                e.*,
                COUNT(a.id) AS action_count,
                GROUP_CONCAT(a.action SEPARATOR ' || ') AS action_preview,
                MAX(r.id) AS reply_id,
                MAX(r.needs_reply) AS reply_needs_reply,
                MAX(r.status) AS reply_status,
                MAX(r.decision_reason) AS reply_reason,
                MAX(r.draft_subject) AS reply_subject,
                MAX(r.draft_body) AS reply_body,
                MAX(r.reviewer_notes) AS reply_reviewer_notes,
                MAX(r.ai_review_notes) AS reply_ai_review_notes,
                MAX(r.ai_review_rounds) AS reply_ai_review_rounds,
                MAX(r.ai_review_passed) AS reply_ai_review_passed,
                MAX(r.sent_at) AS reply_sent_at,
                MAX(r.send_error) AS reply_send_error
            FROM emails e
            LEFT JOIN action_items a ON a.email_id = e.id AND a.deleted_at IS NULL
            LEFT JOIN email_replies r ON r.email_id = e.id
            WHERE {" AND ".join(filters)}
            GROUP BY e.id
            ORDER BY e.date DESC
            LIMIT 200
            """,
            params,
        )
        return [_normalize_email(row) for row in cursor.fetchall()]

    def _get_action_items(self, cursor, since: datetime) -> list[dict]:
        cursor.execute(
            """
            SELECT
                a.id, a.email_id, a.action, a.deadline, a.priority,
                e.subject, e.sender, e.sender_name, e.category, e.date
            FROM action_items a
            JOIN emails e ON a.email_id = e.id
            WHERE e.deleted_at IS NULL
                AND a.deleted_at IS NULL
                AND e.date >= %s
                AND e.mailbox = 'inbox'
            ORDER BY
                CASE a.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                e.date DESC
            LIMIT 100
            """,
            (since,),
        )
        return [
            {
                "id": row["id"],
                "email_id": row["email_id"],
                "action": row.get("action") or "",
                "deadline": row.get("deadline") or "",
                "priority": row.get("priority") or "normal",
                "subject": row.get("subject") or "",
                "sender": row.get("sender") or "",
                "sender_name": _decode_mime_words(row.get("sender_name") or row.get("sender") or ""),
                "category": row.get("category") or "未分类",
                "date": _json_datetime(row.get("date")),
            }
            for row in cursor.fetchall()
        ]

    def _get_category_counts(self, cursor, since: datetime, mailbox: str = "inbox") -> list[dict]:
        mailbox_filter = ""
        params: list[Any] = [since]
        if mailbox == "spam":
            mailbox_filter = " AND mailbox = %s"
            params.append("spam")
        else:
            mailbox_filter = " AND mailbox = %s"
            params.append("inbox")

        cursor.execute(
            f"""
            SELECT COALESCE(category, '未分类') AS category, COUNT(*) AS count
            FROM emails
            WHERE deleted_at IS NULL AND date >= %s{mailbox_filter}
            GROUP BY category
            ORDER BY count DESC, category ASC
            """,
            params,
        )
        return [{"category": row["category"], "count": row["count"]} for row in cursor.fetchall()]

    def _get_top_senders(
        self,
        cursor,
        since: datetime,
        limit: int = 8,
        mailbox: str = "inbox",
    ) -> list[dict]:
        cursor.execute(
            """
            SELECT sender_name, sender, COUNT(*) AS count
            FROM emails
            WHERE deleted_at IS NULL AND date >= %s AND mailbox = %s
            GROUP BY sender_name, sender
            ORDER BY count DESC
            LIMIT %s
            """,
            (since, "spam" if mailbox == "spam" else "inbox", limit),
        )
        return [
            {
                "name": _decode_mime_words(row.get("sender_name") or row.get("sender") or ""),
                "email": row.get("sender") or "",
                "count": row["count"],
            }
            for row in cursor.fetchall()
        ]


def _normalize_email(row: dict) -> dict:
    return {
        "id": row["id"],
        "uid": row.get("uid") or "",
        "account": row.get("account") or "",
        "sender": row.get("sender") or "",
        "sender_name": _decode_mime_words(row.get("sender_name") or row.get("sender") or ""),
        "subject": row.get("subject") or "(无主题)",
        "date": _json_datetime(row.get("date")),
        "category": row.get("category") or "未分类",
        "mailbox": row.get("mailbox") or _mailbox_for_category(row.get("category") or ""),
        "confidence": row.get("confidence") or 0,
        "category_reason": row.get("category_reason") or "",
        "summary": row.get("summary") or "",
        "recipient": row.get("recipient") or "",
        "raw_body_text": row.get("raw_body_text") or "",
        "body_text": row.get("raw_body_text") or "",
        "raw_headers": row.get("raw_headers") or "",
        "attachment_names": _parse_attachment_names(row.get("attachment_names")),
        "has_attachments": bool(row.get("has_attachments")),
        "processed_at": _json_datetime(row.get("processed_at")),
        "action_count": row.get("action_count") or 0,
        "action_preview": row.get("action_preview") or "",
        "reply": _normalize_reply(row),
    }


def _to_mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo:
        return value.replace(tzinfo=None)
    return value


def _json_datetime(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _json_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _decode_mime_words(value: str) -> str:
    if not value:
        return ""
    decoded = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _parse_attachment_names(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return [part.strip() for part in str(value).split("\n") if part.strip()]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return []


def _normalize_reply(row: dict) -> dict | None:
    reply_id = row.get("reply_id")
    if not reply_id:
        return None
    return {
        "id": reply_id,
        "needs_reply": bool(row.get("reply_needs_reply")),
        "status": row.get("reply_status") or "",
        "reason": row.get("reply_reason") or "",
        "subject": row.get("reply_subject") or "",
        "body": row.get("reply_body") or "",
        "reviewer_notes": row.get("reply_reviewer_notes") or "",
        "ai_review_notes": row.get("reply_ai_review_notes") or "",
        "ai_review_rounds": row.get("reply_ai_review_rounds") or 0,
        "ai_review_passed": bool(row.get("reply_ai_review_passed")),
        "sent_at": _json_datetime(row.get("reply_sent_at")),
        "send_error": row.get("reply_send_error") or "",
    }


def _normalize_reply_email(row: dict) -> dict:
    email_data = _normalize_email(row)
    reply = email_data.get("reply") or {}
    return {
        **email_data,
        "reply_id": reply.get("id") or row.get("reply_id"),
        "reply_needs_reply": reply.get("needs_reply", False),
        "reply_status": reply.get("status") or "",
        "reply_reason": reply.get("reason") or "",
        "reply_subject": reply.get("subject") or "",
        "reply_body": reply.get("body") or "",
        "reply_reviewer_notes": reply.get("reviewer_notes") or "",
        "reply_ai_review_notes": reply.get("ai_review_notes") or "",
        "reply_ai_review_rounds": reply.get("ai_review_rounds") or 0,
        "reply_ai_review_passed": reply.get("ai_review_passed", False),
        "reply_sent_at": reply.get("sent_at") or "",
        "reply_send_error": reply.get("send_error") or "",
    }


def _mailbox_for_category(category: str) -> str:
    return "spam" if category == "垃圾邮件" else "inbox"


def _is_unknown_database_error(error: Exception) -> bool:
    args = getattr(error, "args", ())
    return bool(args and args[0] == 1049)
