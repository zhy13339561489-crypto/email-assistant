import unittest

from backend.server import _parse_delete_action


class TestServerRoutes(unittest.TestCase):
    def test_parse_delete_action(self):
        self.assertEqual(_parse_delete_action("/api/emails/12/delete"), (12, "email"))
        self.assertEqual(_parse_delete_action("/api/actions/7/delete"), (7, "action"))
        self.assertIsNone(_parse_delete_action("/api/emails/nope/delete"))
        self.assertIsNone(_parse_delete_action("/api/replies/7/delete"))


if __name__ == "__main__":
    unittest.main()
