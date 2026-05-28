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


if __name__ == "__main__":
    unittest.main()
