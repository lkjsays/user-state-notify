import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reminders  # noqa: E402

KST = timezone(timedelta(hours=9))
FIXED = datetime(2026, 6, 18, 9, 0, 0, tzinfo=KST)


def make_store(tmp, clock=None, gap_min=60):
    return reminders.ReminderStore(
        state_dir=tmp,
        gap_min=gap_min,
        now_fn=clock or (lambda: FIXED),
    )


class AddListDoneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = make_store(self.tmp)

    def test_add_with_device(self):
        r = self.store.add("보고서 작성", device="mac-studio-office")
        self.assertEqual(r["device"], "mac-studio-office")
        self.assertIsNone(r["place"])
        self.assertEqual(r["status"], "pending")
        self.assertEqual(self.store.list(status="pending")[0]["id"], r["id"])

    def test_add_parses_device_token(self):
        r = self.store.add("보고서 작성@회사맥")
        self.assertEqual(r["device"], "mac-studio-office")
        self.assertEqual(r["text"], "보고서 작성")

    def test_add_token_with_place_and_device(self):
        r = self.store.add("점심 메모@회사맥북")
        self.assertEqual(r["device"], "macbook")
        self.assertEqual(r["place"], "office")
        self.assertEqual(r["text"], "점심 메모")

    def test_explicit_arg_wins_over_token(self):
        r = self.store.add("작업@회사맥", device="override-mac")
        self.assertEqual(r["device"], "override-mac")

    def test_add_requires_condition(self):
        with self.assertRaises(ValueError):
            self.store.add("그냥 메모")

    def test_add_requires_text(self):
        with self.assertRaises(ValueError):
            self.store.add("@회사맥")

    def test_unknown_token_kept_in_text(self):
        r = self.store.add("정리@모르는곳", device="d1")
        self.assertIn("@모르는곳", r["text"])

    def test_list_filter_status(self):
        a = self.store.add("a", device="d1")
        self.store.add("b", device="d1")
        self.store.mark_done(a["id"])
        pending = self.store.list(status="pending")
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(self.store.list()), 2)

    def test_mark_done(self):
        r = self.store.add("x", device="d1")
        done = self.store.mark_done(r["id"])
        self.assertEqual(done["status"], "done")
        self.assertIsNotNone(done["done_at"])
        self.assertEqual(self.store.list(status="pending"), [])

    def test_mark_done_idempotent(self):
        r = self.store.add("x", device="d1")
        self.store.mark_done(r["id"])
        again = self.store.mark_done(r["id"])
        self.assertEqual(again["status"], "done")

    def test_mark_done_missing(self):
        self.assertIsNone(self.store.mark_done("r_nope"))

    def test_aliases_file_autocreated(self):
        self.store.add("x", device="d1")  # triggers alias load
        path = Path(self.tmp) / "reminder_aliases.json"
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
