import unittest
from types import SimpleNamespace

from src.ai_engine import AIEngine


class TestAIEngine(unittest.TestCase):
    def setUp(self):
        self.engine = AIEngine(api_key="test-key", categories=["工作", "其他"])

    def test_parse_json_valid(self):
        result = self.engine._parse_json('{"category": "工作", "confidence": 0.9}')
        self.assertEqual(result["category"], "工作")

    def test_parse_json_with_markdown(self):
        text = '```json\n{"category": "工作"}\n```'
        result = self.engine._parse_json(text)
        self.assertEqual(result["category"], "工作")

    def test_parse_json_array(self):
        result = self.engine._parse_json('[{"action": "回复"}]')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "回复")

    def test_parse_json_invalid(self):
        result = self.engine._parse_json("not json at all")
        self.assertEqual(result, [])

    def test_call_api_uses_langchain_llm(self):
        class FakeLLM:
            def invoke(self, messages):
                self.messages = messages
                return SimpleNamespace(content='{"ok": true}')

        fake_llm = FakeLLM()
        self.engine._llm = fake_llm
        self.engine._to_langchain_messages = lambda messages: messages

        result = self.engine._call_api([{"role": "user", "content": "hello"}])

        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(fake_llm.messages[0]["content"], "hello")

    def test_reply_decision_and_draft_use_json(self):
        class FakeLLM:
            def __init__(self):
                self.responses = [
                    '{"needs_reply": true, "reason": "对方提出问题"}',
                    '{"subject": "Re: Hello", "body": "您好，已收到。"}',
                ]

            def invoke(self, messages):
                return SimpleNamespace(content=self.responses.pop(0))

        from datetime import datetime
        from src.models import ClassificationResult, EmailData, ProcessResult

        email = EmailData(
            uid="1",
            subject="Hello",
            sender="sender@example.com",
            sender_name="Sender",
            to="me@example.com",
            date=datetime(2026, 5, 28, 18, 0),
            body_text="请确认是否收到。",
        )
        process_result = ProcessResult(
            classification=ClassificationResult("工作", 0.9, "reason"),
            summary="请求确认",
        )
        self.engine._llm = FakeLLM()
        self.engine._to_langchain_messages = lambda messages: messages

        decision = self.engine.decide_reply(email, process_result)
        draft = self.engine.draft_reply(email, process_result)

        self.assertTrue(decision.needs_reply)
        self.assertEqual(draft.subject, "Re: Hello")
        self.assertIn("已收到", draft.body)

    def test_refine_reply_with_reviewer_loops_until_approved(self):
        class FakeWriterLLM:
            def invoke(self, messages):
                return SimpleNamespace(content='{"subject": "Re: Hello", "body": "您好，已补充说明。"}')

        class FakeReviewerLLM:
            def __init__(self):
                self.responses = [
                    '{"approved": false, "comments": "需要更具体", "reason": "回复偏空泛"}',
                    '{"approved": true, "comments": "可以发送", "reason": "内容准确礼貌"}',
                ]

            def invoke(self, messages):
                return SimpleNamespace(content=self.responses.pop(0))

        from src.models import ReplyDraft

        self.engine._llm = FakeWriterLLM()
        self.engine._review_llm = FakeReviewerLLM()
        self.engine._to_langchain_messages = lambda messages: messages

        draft = self.engine.refine_reply_with_reviewer(
            {
                "sender": "sender@example.com",
                "sender_name": "Sender",
                "recipient": "me@example.com",
                "subject": "Hello",
                "summary": "请求确认",
                "raw_body_text": "请确认。",
            },
            ReplyDraft("Re: Hello", "您好。"),
            max_rounds=2,
        )

        self.assertTrue(draft.review_passed)
        self.assertEqual(draft.review_rounds, 2)
        self.assertIn("补充说明", draft.body)


if __name__ == "__main__":
    unittest.main()
