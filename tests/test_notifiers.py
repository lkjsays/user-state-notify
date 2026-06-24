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
