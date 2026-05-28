import unittest
from datetime import datetime

from backend.storage import _mailbox_for_category, _normalize_email


class TestMySQLStorageHelpers(unittest.TestCase):
    def test_mailbox_for_category(self):
        self.assertEqual(_mailbox_for_category("垃圾邮件"), "spam")
        self.assertEqual(_mailbox_for_category("工作"), "inbox")
        self.assertEqual(_mailbox_for_category("订阅通知"), "inbox")

    def test_normalize_email_assigns_mailbox(self):
        row = {
            "id": 1,
            "uid": "5",
            "account": "user",
            "sender": "sender@example.com",
            "sender_name": "Sender",
            "subject": "Hello",
            "date": datetime(2026, 5, 28, 17, 55),
            "category": "垃圾邮件",
            "confidence": 0.9,
            "category_reason": "reason",
            "summary": "summary",
            "recipient": "to@example.com",
            "raw_body_text": "raw body",
            "raw_headers": "Subject: Hello",
            "attachment_names": '["a.pdf", "b.txt"]',
            "has_attachments": 0,
            "processed_at": datetime(2026, 5, 28, 17, 56),
            "action_count": 0,
            "action_preview": "",
        }

        result = _normalize_email(row)

        self.assertEqual(result["mailbox"], "spam")
        self.assertEqual(result["date"], "2026-05-28T17:55:00")
        self.assertEqual(result["recipient"], "to@example.com")
        self.assertEqual(result["raw_body_text"], "raw body")
        self.assertEqual(result["raw_headers"], "Subject: Hello")
        self.assertEqual(result["attachment_names"], ["a.pdf", "b.txt"])
        self.assertIsNone(result["reply"])

    def test_normalize_email_includes_reply(self):
        row = {
            "id": 1,
            "uid": "5",
            "account": "user",
            "sender": "sender@example.com",
            "sender_name": "Sender",
            "subject": "Hello",
            "date": datetime(2026, 5, 28, 17, 55),
            "category": "工作",
            "confidence": 0.9,
            "category_reason": "reason",
            "summary": "summary",
            "has_attachments": 0,
            "processed_at": datetime(2026, 5, 28, 17, 56),
            "action_count": 0,
            "action_preview": "",
            "reply_id": 8,
            "reply_needs_reply": 1,
            "reply_status": "pending_review",
            "reply_reason": "needs answer",
            "reply_subject": "Re: Hello",
            "reply_body": "Thanks",
            "reply_reviewer_notes": "",
            "reply_sent_at": None,
            "reply_send_error": "",
        }

        result = _normalize_email(row)

        self.assertEqual(result["reply"]["id"], 8)
        self.assertTrue(result["reply"]["needs_reply"])
        self.assertEqual(result["reply"]["status"], "pending_review")
        self.assertEqual(result["reply"]["subject"], "Re: Hello")


if __name__ == "__main__":
    unittest.main()
