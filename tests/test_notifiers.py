import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import notifiers  # noqa: E402


class LoadConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_valid_config(self):
        p = self.tmp / "config.json"
        p.write_text(json.dumps({"notifiers": [{"type": "telegram"}]}), encoding="utf-8")
        config, err = notifiers.load_config(p)
        self.assertIsNone(err)
        self.assertEqual(config["notifiers"][0]["type"], "telegram")

    def test_missing_file(self):
        config, err = notifiers.load_config(self.tmp / "nope.json")
        self.assertIsNone(config)
        self.assertIn("not found", err)

    def test_broken_json(self):
        p = self.tmp / "config.json"
        p.write_text("{ not json", encoding="utf-8")
        config, err = notifiers.load_config(p)
        self.assertIsNone(config)
        self.assertIn("invalid", err.lower())


class FakeHTTP:
    def __init__(self, result=(True, "200 ok")):
        self.result = result
        self.calls = []

    def __call__(self, url, data, headers, timeout=10):
        self.calls.append({"url": url, "data": data, "headers": headers})
        return self.result


class TelegramTests(unittest.TestCase):
    def test_send_posts_to_bot_api(self):
        http = FakeHTTP()
        n = notifiers.TelegramNotifier(
            {"bot_token": "TK", "chat_id": "42"}, http_post=http
        )
        ok, detail = n.send("안녕", {"type": "device.login"})
        self.assertTrue(ok)
        self.assertEqual(n.type, "telegram")
        self.assertIn("/botTK/sendMessage", http.calls[0]["url"])
        payload = json.loads(http.calls[0]["data"].decode("utf-8"))
        self.assertEqual(payload["chat_id"], "42")
        self.assertEqual(payload["text"], "안녕")

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            notifiers.TelegramNotifier({"bot_token": "TK"})
