import unittest
from unittest.mock import patch, MagicMock
from email.mime.text import MIMEText

from src.fetcher import EmailFetcher


class TestEmailFetcher(unittest.TestCase):
    def setUp(self):
        self.fetcher = EmailFetcher(
            address="test@example.com",
            imap_server="imap.example.com",
            imap_port=993,
            password="password",
        )

    def test_decode_header_plain(self):
        result = self.fetcher._decode_header("Hello World")
        self.assertEqual(result, "Hello World")

    def test_decode_header_encoded(self):
        from email.header import Header
        header = Header("测试邮件", "utf-8").encode()
        result = self.fetcher._decode_header(header)
        self.assertEqual(result, "测试邮件")

    def test_extract_body_plain(self):
        msg = MIMEText("这是纯文本正文", "plain", "utf-8")
        result = self.fetcher._extract_body(msg)
        self.assertIn("这是纯文本正文", result)

    def test_extract_body_html(self):
        msg = MIMEText("<html><body><p>HTML正文</p></body></html>", "html", "utf-8")
        result = self.fetcher._extract_body(msg)
        self.assertIn("HTML正文", result)
        self.assertNotIn("<p>", result)

    def test_extract_attachment_names_none(self):
        msg = MIMEText("plain text")
        result = self.fetcher._extract_attachment_names(msg)
        self.assertEqual(result, [])

    def test_send_imap_id_for_netease_server(self):
        self.fetcher.imap_server = "imap.163.com"
        self.fetcher.conn = MagicMock()
        self.fetcher.conn._simple_command.return_value = ("OK", [b'ID ("name" "EmailAI")'])

        self.fetcher._send_imap_id_if_needed()

        self.fetcher.conn._simple_command.assert_called_once()
        command, args = self.fetcher.conn._simple_command.call_args.args
        self.assertEqual(command, "ID")
        self.assertIn('"name" "EmailAI"', args)
        self.fetcher.conn._untagged_response.assert_called_once_with(
            "OK", [b'ID ("name" "EmailAI")'], "ID"
        )

    def test_skip_imap_id_when_server_does_not_need_it(self):
        self.fetcher.conn = MagicMock()
        self.fetcher.conn.capability.return_value = ("OK", [b"IMAP4rev1 AUTH=PLAIN"])

        self.fetcher._send_imap_id_if_needed()

        self.fetcher.conn._simple_command.assert_not_called()

    def test_select_inbox_reports_unsafe_login(self):
        self.fetcher.conn = MagicMock()
        self.fetcher.conn.select.return_value = (
            "NO",
            [b"SELECT Unsafe Login. Please contact kefu@188.com for help"],
        )

        with self.assertRaisesRegex(RuntimeError, "Unsafe Login"):
            self.fetcher._select_inbox()


if __name__ == "__main__":
    unittest.main()
