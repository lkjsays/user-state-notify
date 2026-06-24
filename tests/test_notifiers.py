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


class WebhookTests(unittest.TestCase):
    def test_send_posts_json_with_headers(self):
        http = FakeHTTP()
        n = notifiers.WebhookNotifier(
            {"url": "https://h.example/hook", "headers": {"Authorization": "Bearer X"}},
            http_post=http,
        )
        ok, _ = n.send("메모", {"type": "device.wake"})
        self.assertTrue(ok)
        self.assertEqual(n.type, "webhook")
        call = http.calls[0]
        self.assertEqual(call["url"], "https://h.example/hook")
        self.assertEqual(call["headers"]["Authorization"], "Bearer X")
        self.assertEqual(call["headers"]["Content-Type"], "application/json; charset=utf-8")
        body = json.loads(call["data"].decode("utf-8"))
        self.assertEqual(body["message"], "메모")
        self.assertEqual(body["text"], "메모")
        self.assertEqual(body["event"]["type"], "device.wake")

    def test_missing_url_raises(self):
        with self.assertRaises(ValueError):
            notifiers.WebhookNotifier({})


class FakeProc:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class HermesTests(unittest.TestCase):
    def test_send_invokes_webhook_test_primary(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            return FakeProc(returncode=0, stdout="delivered")

        n = notifiers.HermesNotifier({"webhook_name": "wh"}, runner=runner)
        ok, detail = n.send("hi", {"type": "device.login"})
        self.assertTrue(ok)
        self.assertEqual(n.type, "hermes")
        # primary command is `webhook test --payload`; the binary path is
        # machine-resolved, so assert on the subcommand portion only.
        self.assertEqual(calls[0][1:4], ["webhook", "test", "wh"])
        self.assertIn("--payload", calls[0])

    def test_send_falls_back_through_candidates(self):
        seq = [
            FakeProc(returncode=1, stderr="no test"),
            FakeProc(returncode=0, stdout="triggered"),
        ]
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            return seq.pop(0)

        n = notifiers.HermesNotifier({}, runner=runner)  # default webhook_name
        ok, _ = n.send("hi", {})
        self.assertTrue(ok)
        # fell back from `test` to `trigger`
        self.assertEqual(calls[0][1:3], ["webhook", "test"])
        self.assertEqual(calls[1][1:3], ["webhook", "trigger"])


class BuildNotifiersTests(unittest.TestCase):
    def test_builds_enabled_only_and_records_errors(self):
        http = FakeHTTP()
        config = {"notifiers": [
            {"type": "telegram", "enabled": True, "bot_token": "T", "chat_id": "1"},
            {"type": "webhook", "enabled": False, "url": "https://x"},
            {"type": "telegram", "enabled": True, "bot_token": "T"},   # missing chat_id
            {"type": "mystery", "enabled": True},                       # unknown type
        ]}
        ns, errors = notifiers.build_notifiers(config, http_post=http)
        self.assertEqual([n.type for n in ns], ["telegram"])
        self.assertEqual(len(errors), 2)

    def test_enabled_defaults_true(self):
        config = {"notifiers": [{"type": "webhook", "url": "https://x"}]}
        ns, errors = notifiers.build_notifiers(config)
        self.assertEqual(len(ns), 1)
        self.assertEqual(errors, [])


class NotifyTests(unittest.TestCase):
    def test_fanout_partial_failure_is_any_ok(self):
        ok_http = FakeHTTP((True, "200"))
        bad_http = FakeHTTP((False, "boom"))
        ns = [
            notifiers.TelegramNotifier({"bot_token": "T", "chat_id": "1"}, http_post=ok_http),
            notifiers.WebhookNotifier({"url": "https://x"}, http_post=bad_http),
        ]
        any_ok, results = notifiers.notify("m", {"type": "device.wake"}, ns)
        self.assertTrue(any_ok)
        self.assertEqual([r["ok"] for r in results], [True, False])

    def test_all_fail(self):
        bad = FakeHTTP((False, "boom"))
        ns = [notifiers.WebhookNotifier({"url": "https://x"}, http_post=bad)]
        any_ok, results = notifiers.notify("m", {}, ns)
        self.assertFalse(any_ok)

    def test_empty_notifiers(self):
        any_ok, results = notifiers.notify("m", {}, [])
        self.assertFalse(any_ok)
        self.assertEqual(results, [])

    def test_exception_in_one_does_not_block_others(self):
        class Boom:
            type = "boom"
            def send(self, message, event):
                raise RuntimeError("kaboom")
        ok_http = FakeHTTP((True, "200"))
        ns = [Boom(), notifiers.TelegramNotifier({"bot_token": "T", "chat_id": "1"}, http_post=ok_http)]
        any_ok, results = notifiers.notify("m", {}, ns)
        self.assertTrue(any_ok)
        self.assertFalse(results[0]["ok"])
        self.assertIn("kaboom", results[0]["detail"])
        self.assertTrue(results[1]["ok"])
