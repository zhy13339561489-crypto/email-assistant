import unittest
from unittest.mock import patch, MagicMock

from src.ai_engine import AIEngine


class TestAIEngine(unittest.TestCase):
    def setUp(self):
        with patch("src.ai_engine.OpenAI"):
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


if __name__ == "__main__":
    unittest.main()
