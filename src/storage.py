import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

from loguru import logger

from .models import EmailData, ProcessResult, ActionItem


class EmailStorage:
    def __init__(self, db_path: str = "data/emails.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT,
                    account TEXT,
                    sender TEXT,
                    sender_name TEXT,
                    subject TEXT,
                    date DATETIME,
                    category TEXT,
                    confidence REAL,
                    category_reason TEXT,
                    summary TEXT,
                    has_attachments BOOLEAN DEFAULT 0,
                    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS action_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id INTEGER REFERENCES emails(id),
                    action TEXT,
                    deadline TEXT,
                    priority TEXT DEFAULT 'normal'
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_email_uid ON emails(uid);
                CREATE INDEX IF NOT EXISTS idx_email_category ON emails(category);
                CREATE INDEX IF NOT EXISTS idx_email_date ON emails(date);
            """)
        logger.info(f"数据库初始化完成: {self.db_path}")

    def save_result(self, email_data: EmailData, result: ProcessResult,
                    account: str = "") -> int:
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT OR REPLACE INTO emails
                (uid, account, sender, sender_name, subject, date,
                 category, confidence, category_reason, summary, has_attachments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                email_data.uid, account, email_data.sender,
                email_data.sender_name, email_data.subject,
                email_data.date.isoformat(),
                result.classification.category,
                result.classification.confidence,
                result.classification.reason,
                result.summary,
                email_data.has_attachments,
            ))
            email_id = cursor.lastrowid

            # 清除旧的 action items
            conn.execute("DELETE FROM action_items WHERE email_id = ?", (email_id,))

            # 插入新的 action items
            for item in result.action_items:
                conn.execute("""
                    INSERT INTO action_items (email_id, action, deadline, priority)
                    VALUES (?, ?, ?, ?)
                """, (email_id, item.action, item.deadline, item.priority))

            return email_id

    def get_by_category(self, category: str, days: int = 7) -> list[dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM emails
                WHERE category = ? AND date >= ?
                ORDER BY date DESC
            """, (category, since)).fetchall()
            return [dict(r) for r in rows]

    def get_today_emails(self) -> list[dict]:
        today = date.today().isoformat()
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM emails
                WHERE date >= ?
                ORDER BY date DESC
            """, (today,)).fetchall()
            return [dict(r) for r in rows]

    def get_action_items(self, days: int = 7) -> list[dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT a.*, e.subject, e.sender
                FROM action_items a
                JOIN emails e ON a.email_id = e.id
                WHERE e.date >= ?
                ORDER BY
                    CASE a.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    e.date DESC
            """, (since,)).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self, days: int = 30) -> dict:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as c FROM emails WHERE date >= ?", (since,)
            ).fetchone()["c"]

            by_category = conn.execute("""
                SELECT category, COUNT(*) as count FROM emails
                WHERE date >= ? GROUP BY category ORDER BY count DESC
            """, (since,)).fetchall()

            top_senders = conn.execute("""
                SELECT sender_name, sender, COUNT(*) as count FROM emails
                WHERE date >= ? GROUP BY sender ORDER BY count DESC LIMIT 10
            """, (since,)).fetchall()

            return {
                "total": total,
                "by_category": {r["category"]: r["count"] for r in by_category},
                "top_senders": [
                    {"name": r["sender_name"], "email": r["sender"], "count": r["count"]}
                    for r in top_senders
                ],
            }
