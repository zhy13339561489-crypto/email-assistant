from __future__ import annotations

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
                confidence DOUBLE,
                category_reason TEXT,
                summary TEXT,
                has_attachments TINYINT(1) DEFAULT 0,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY idx_email_uid_account (uid, account),
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
        ]
        conn = self._connect_database_or_create()
        with conn:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
            conn.commit()
        logger.info(f"MySQL 数据库初始化完成: {self.config.host}:{self.config.port}/{self.config.database}")

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
                     category, confidence, category_reason, summary, has_attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id),
                        sender = VALUES(sender),
                        sender_name = VALUES(sender_name),
                        subject = VALUES(subject),
                        date = VALUES(date),
                        category = VALUES(category),
                        confidence = VALUES(confidence),
                        category_reason = VALUES(category_reason),
                        summary = VALUES(summary),
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
                        result.classification.confidence,
                        result.classification.reason,
                        result.summary,
                        int(email_data.has_attachments),
                    ),
                )
                email_id = cursor.lastrowid
                cursor.execute("DELETE FROM action_items WHERE email_id = %s", (email_id,))
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

    def get_emails_between(self, start: datetime, end: datetime) -> list[dict]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        e.*,
                        COUNT(a.id) AS action_count,
                        GROUP_CONCAT(a.action SEPARATOR ' || ') AS action_preview
                    FROM emails e
                    LEFT JOIN action_items a ON a.email_id = e.id
                    WHERE e.date >= %s AND e.date < %s
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

    def get_dashboard(self, days: int = 30, category: str = "all", query: str = "") -> dict:
        days = max(1, min(int(days or 30), 365))
        category = (category or "all").strip()
        query = (query or "").strip()
        since = datetime.now() - timedelta(days=days)

        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                emails = self._get_emails(cursor, since, category, query)
                action_items = self._get_action_items(cursor, since)
                categories = self._get_category_counts(cursor, since)
                top_senders = self._get_top_senders(cursor, since)

        total = len(emails)
        with_actions = sum(1 for item in emails if item["action_count"] > 0)
        avg_confidence = round(sum(item["confidence"] or 0 for item in emails) / total, 3) if total else 0
        attachments = sum(1 for item in emails if item["has_attachments"])

        return {
            "meta": {
                "days": days,
                "category": category or "all",
                "query": query,
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
                    "SELECT * FROM emails WHERE date >= %s ORDER BY date DESC",
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
                cursor.execute("SELECT COUNT(*) AS c FROM emails WHERE date >= %s", (since,))
                total = cursor.fetchone()["c"]
                categories = self._get_category_counts(cursor, since)
                top_senders = self._get_top_senders(cursor, since, limit=10)
        return {
            "total": total,
            "by_category": {item["category"]: item["count"] for item in categories},
            "top_senders": top_senders,
        }

    def _get_emails(self, cursor, since: datetime, category: str, query: str) -> list[dict]:
        filters = ["e.date >= %s"]
        params: list[Any] = [since]
        if category and category != "all":
            filters.append("e.category = %s")
            params.append(category)
        if query:
            like = f"%{query}%"
            filters.append(
                "(e.subject LIKE %s OR e.summary LIKE %s OR e.sender LIKE %s OR e.sender_name LIKE %s)"
            )
            params.extend([like, like, like, like])

        cursor.execute(
            f"""
            SELECT
                e.*,
                COUNT(a.id) AS action_count,
                GROUP_CONCAT(a.action SEPARATOR ' || ') AS action_preview
            FROM emails e
            LEFT JOIN action_items a ON a.email_id = e.id
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
            WHERE e.date >= %s
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

    def _get_category_counts(self, cursor, since: datetime) -> list[dict]:
        cursor.execute(
            """
            SELECT COALESCE(category, '未分类') AS category, COUNT(*) AS count
            FROM emails
            WHERE date >= %s
            GROUP BY category
            ORDER BY count DESC, category ASC
            """,
            (since,),
        )
        return [{"category": row["category"], "count": row["count"]} for row in cursor.fetchall()]

    def _get_top_senders(self, cursor, since: datetime, limit: int = 8) -> list[dict]:
        cursor.execute(
            """
            SELECT sender_name, sender, COUNT(*) AS count
            FROM emails
            WHERE date >= %s
            GROUP BY sender_name, sender
            ORDER BY count DESC
            LIMIT %s
            """,
            (since, limit),
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
        "confidence": row.get("confidence") or 0,
        "category_reason": row.get("category_reason") or "",
        "summary": row.get("summary") or "",
        "has_attachments": bool(row.get("has_attachments")),
        "processed_at": _json_datetime(row.get("processed_at")),
        "action_count": row.get("action_count") or 0,
        "action_preview": row.get("action_preview") or "",
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


def _is_unknown_database_error(error: Exception) -> bool:
    args = getattr(error, "args", ())
    return bool(args and args[0] == 1049)
