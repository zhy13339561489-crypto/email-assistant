import sqlite3
import unittest
from datetime import datetime
from email.header import Header

from src.dashboard import DashboardData


class TestDashboardData(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE emails (
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

            CREATE TABLE action_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER REFERENCES emails(id),
                action TEXT,
                deadline TEXT,
                priority TEXT DEFAULT 'normal'
            );
            """
        )

        now = datetime.now().isoformat()
        encoded_name = Header("项目经理", "utf-8").encode()
        self.conn.execute(
            """
            INSERT INTO emails
            (uid, account, sender, sender_name, subject, date, category,
             confidence, category_reason, summary, has_attachments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dashboard-1",
                "work",
                "pm@example.com",
                encoded_name,
                "项目周会纪要",
                now,
                "工作",
                0.9,
                "项目协作相关",
                "同步项目进展，并需要跟进排期。",
                0,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO emails
            (uid, account, sender, sender_name, subject, date, category,
             confidence, category_reason, summary, has_attachments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dashboard-2",
                "user",
                "shop@example.com",
                "Shop",
                "优惠通知",
                now,
                "促销广告",
                0.8,
                "营销内容",
                "商品折扣信息。",
                1,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO action_items (email_id, action, deadline, priority)
            VALUES (?, ?, ?, ?)
            """,
            (1, "确认下周排期", "明天", "high"),
        )
        self.conn.commit()

        self.dashboard = DashboardData(":memory:")
        self.dashboard._get_conn = lambda: self.conn

    def tearDown(self):
        self.conn.close()

    def test_dashboard_summary(self):
        data = self.dashboard.get_dashboard(days=30)

        self.assertEqual(data["stats"]["total"], 2)
        self.assertEqual(data["stats"]["with_actions"], 1)
        self.assertEqual(data["stats"]["attachments"], 1)
        self.assertEqual(len(data["action_items"]), 1)
        self.assertEqual(data["action_items"][0]["sender_name"], "项目经理")

    def test_dashboard_filters_by_category_and_query(self):
        data = self.dashboard.get_dashboard(
            days=30,
            category="工作",
            query="排期",
        )

        self.assertEqual(data["stats"]["total"], 1)
        self.assertEqual(data["emails"][0]["subject"], "项目周会纪要")
        self.assertEqual(data["emails"][0]["action_count"], 1)


if __name__ == "__main__":
    unittest.main()
