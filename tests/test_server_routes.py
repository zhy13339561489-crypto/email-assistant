import unittest
from types import SimpleNamespace

from loguru import logger

from backend.server import BackendRuntime, _parse_delete_action


class TestServerRoutes(unittest.TestCase):
    def test_parse_delete_action(self):
        self.assertEqual(_parse_delete_action("/api/emails/12/delete"), (12, "email"))
        self.assertEqual(_parse_delete_action("/api/actions/7/delete"), (7, "action"))
        self.assertIsNone(_parse_delete_action("/api/emails/nope/delete"))
        self.assertIsNone(_parse_delete_action("/api/replies/7/delete"))

    def test_revise_reply_returns_json_error_when_ai_fails(self):
        class FakeStorage:
            def get_reply_with_email(self, reply_id):
                return {
                    "id": reply_id,
                    "reply_subject": "Re: Test",
                    "reply_body": "old body",
                }

        class FailingAI:
            def revise_reply(self, reply, subject, body, notes):
                raise RuntimeError("Connection error.")

        runtime = BackendRuntime.__new__(BackendRuntime)
        runtime.storage = FakeStorage()
        runtime.processor = SimpleNamespace(ai=FailingAI())

        logger.disable("backend.server")
        try:
            result = runtime.revise_reply(1, {"reviewer_notes": "请修改"})
        finally:
            logger.enable("backend.server")

        self.assertFalse(result["ok"])
        self.assertIn("AI 修改失败", result["error"])
        self.assertIn("Connection error", result["error"])


if __name__ == "__main__":
    unittest.main()
