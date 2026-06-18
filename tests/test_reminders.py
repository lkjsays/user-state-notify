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


class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, minutes):
        self.t = self.t + timedelta(minutes=minutes)


class EventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clock = Clock(FIXED)
        self.store = make_store(self.tmp, clock=self.clock, gap_min=60)
        self.sent = []
        self.forward = lambda msg: (self.sent.append(msg) or True)

    def ev(self, etype, device="mac-studio-office", place="office"):
        return {
            "type": etype,
            "device": device,
            "place": place,
            "timestamp": self.clock().isoformat(timespec="seconds"),
        }

    def test_login_fires_and_forwards(self):
        self.store.add("보고서", device="mac-studio-office")
        fired = self.store.on_device_event(self.ev("device.login"), self.forward)
        self.assertEqual(len(fired), 1)
        self.assertEqual(len(self.sent), 1)

    def test_same_session_unlock_no_refire(self):
        self.store.add("보고서", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.clock.advance(5)
        fired = self.store.on_device_event(self.ev("device.unlock"), self.forward)
        self.assertEqual(fired, [])

    def test_long_gap_unlock_refires(self):
        self.store.add("보고서", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.clock.advance(90)
        fired = self.store.on_device_event(self.ev("device.unlock"), self.forward)
        self.assertEqual(len(fired), 1)

    def test_long_gap_wake_refires(self):
        self.store.add("보고서", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.clock.advance(90)
        fired = self.store.on_device_event(self.ev("device.wake"), self.forward)
        self.assertEqual(len(fired), 1)

    def test_added_midsession_fires_next_event(self):
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.store.add("보고서", device="mac-studio-office")
        self.clock.advance(5)
        fired = self.store.on_device_event(self.ev("device.unlock"), self.forward)
        self.assertEqual(len(fired), 1)

    def test_place_match_any_device(self):
        self.store.add("회사일", place="office")
        fired = self.store.on_device_event(
            self.ev("device.login", device="some-other-mac", place="office"), self.forward
        )
        self.assertEqual(len(fired), 1)

    def test_place_mismatch(self):
        self.store.add("집안일", place="home")
        fired = self.store.on_device_event(self.ev("device.login", place="office"), self.forward)
        self.assertEqual(fired, [])

    def test_and_requires_both(self):
        self.store.add("x", place="office", device="mac-studio-office")
        f1 = self.store.on_device_event(
            self.ev("device.login", place=None), self.forward
        )
        self.assertEqual(f1, [])
        self.clock.advance(120)
        f2 = self.store.on_device_event(self.ev("device.login", place="office"), self.forward)
        self.assertEqual(len(f2), 1)

    def test_done_not_fired(self):
        r = self.store.add("x", device="d")
        self.store.mark_done(r["id"])
        fired = self.store.on_device_event(
            self.ev("device.login", device="d", place=None), self.forward
        )
        self.assertEqual(fired, [])

    def test_forward_failure_not_recorded_then_retries(self):
        self.store.add("x", device="d")
        fired = self.store.on_device_event(
            self.ev("device.login", device="d", place=None), lambda m: False
        )
        self.assertEqual(fired, [])
        self.clock.advance(5)
        retry_sent = []
        fired2 = self.store.on_device_event(
            self.ev("device.unlock", device="d", place=None),
            lambda m: retry_sent.append(m) or True,
        )
        self.assertEqual(len(fired2), 1)

    def test_message_contains_text_and_id(self):
        r = self.store.add("보고서 작성", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.assertIn("보고서 작성", self.sent[0])
        self.assertIn(r["id"], self.sent[0])

    def test_naive_timestamp_event_still_fires(self):
        self.store.add("보고서", device="mac-studio-office")
        event = {
            "type": "device.login",
            "device": "mac-studio-office",
            "place": "office",
            "timestamp": "2026-06-18T09:00:00",  # naive, no offset
        }
        fired = self.store.on_device_event(event, self.forward)
        self.assertEqual(len(fired), 1)


if __name__ == "__main__":
    unittest.main()
