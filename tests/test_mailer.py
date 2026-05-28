import unittest

from backend.mailer import _extract_header


class TestSMTPReplyMailer(unittest.TestCase):
    def test_extract_header(self):
        headers = "Subject: Hello\nMessage-ID: <abc@example.com>\nFrom: sender@example.com"

        self.assertEqual(_extract_header(headers, "Message-ID"), "<abc@example.com>")
        self.assertEqual(_extract_header(headers, "References"), "")


if __name__ == "__main__":
    unittest.main()
