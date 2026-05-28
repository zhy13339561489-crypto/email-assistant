import unittest
from datetime import datetime

from src.models import EmailData
from src.preprocessor import EmailPreprocessor


class TestEmailPreprocessor(unittest.TestCase):
    def setUp(self):
        self.preprocessor = EmailPreprocessor(max_body_length=500)

    def _make_email(self, body: str) -> EmailData:
        return EmailData(
            uid="1",
            subject="Test",
            sender="test@example.com",
            sender_name="Test",
            to="me@example.com",
            date=datetime.now(),
            body_text=body,
        )

    def test_clean_signature(self):
        body = "请查看附件。\n\n-- \nBest regards,\n张三"
        result = self.preprocessor.clean_text(body)
        self.assertNotIn("Best regards", result)
        self.assertIn("请查看附件", result)

    def test_clean_forward(self):
        body = "请看下面。\n\n---------- Forwarded message ----------\nFrom: other@example.com"
        result = self.preprocessor.clean_text(body)
        self.assertIn("请看下面", result)
        self.assertNotIn("Forwarded", result)

    def test_truncate_short(self):
        text = "短文本"
        result = self.preprocessor.truncate(text)
        self.assertEqual(result, text)

    def test_truncate_long(self):
        text = "a" * 1000
        result = self.preprocessor.truncate(text)
        self.assertLess(len(result), len(text))
        self.assertIn("截断", result)

    def test_build_context(self):
        email_data = self._make_email("这是正文内容")
        context = self.preprocessor.build_context(email_data)
        self.assertIn("test@example.com", context)
        self.assertIn("Test", context)
        self.assertIn("这是正文内容", context)

    def test_build_context_with_attachments(self):
        email_data = self._make_email("正文")
        email_data.has_attachments = True
        email_data.attachment_names = ["report.pdf", "data.xlsx"]
        context = self.preprocessor.build_context(email_data)
        self.assertIn("report.pdf", context)


if __name__ == "__main__":
    unittest.main()
