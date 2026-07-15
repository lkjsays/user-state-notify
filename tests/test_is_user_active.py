import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "is_user_active.sh"

# ioreg 호출을 가로채는 가짜 바이너리. 환경 변수로 시나리오를 제어한다:
#   FAKE_LOCKED=true|false     IOConsoleLocked 값
#   FAKE_IDLE_NS=<nanoseconds> HIDIdleTime 값
#   FAKE_NO_IDLE=1             HIDIdleTime 키 자체를 생략
#   FAKE_IOREG_FAIL=1          ioreg가 비정상 종료
FAKE_IOREG = r"""#!/bin/bash
if [ "${FAKE_IOREG_FAIL:-}" = "1" ]; then exit 1; fi
case "$*" in
  *"-n Root"*)
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>IOConsoleLocked</key>
  <${FAKE_LOCKED:-false}/>
</dict>
</plist>
EOF
    ;;
  *"-c IOHIDSystem"*)
    if [ "${FAKE_NO_IDLE:-}" = "1" ]; then
      echo '      "SomethingElse" = 1'
    else
      echo "      \"HIDIdleTime\" = ${FAKE_IDLE_NS:-0}"
    fi
    ;;
esac
"""


class IsUserActiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        fake = self.tmp / "ioreg"
        fake.write_text(FAKE_IOREG, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    def run_script(self, extra_env=None, args=()):
        env = os.environ.copy()
        env["PATH"] = f"{self.tmp}:{env['PATH']}"
        env.update(extra_env or {})
        return subprocess.run(
            [str(SCRIPT), *args], env=env,
            capture_output=True, text=True, timeout=10,
        )

    def test_unlocked_and_recent_input_is_active(self):
        r = self.run_script({"FAKE_LOCKED": "false", "FAKE_IDLE_NS": str(30 * 10**9)})
        self.assertEqual(r.returncode, 0)

    def test_unlocked_but_idle_too_long_is_inactive(self):
        r = self.run_script({"FAKE_LOCKED": "false", "FAKE_IDLE_NS": str(600 * 10**9)})
        self.assertEqual(r.returncode, 1)

    def test_locked_is_inactive_even_with_recent_input(self):
        r = self.run_script({"FAKE_LOCKED": "true", "FAKE_IDLE_NS": str(5 * 10**9)})
        self.assertEqual(r.returncode, 1)

    def test_missing_idle_key_fails_open(self):
        r = self.run_script({"FAKE_LOCKED": "false", "FAKE_NO_IDLE": "1"})
        self.assertEqual(r.returncode, 1)

    def test_ioreg_failure_fails_open(self):
        r = self.run_script({"FAKE_IOREG_FAIL": "1"})
        self.assertEqual(r.returncode, 1)

    def test_threshold_env_override(self):
        r = self.run_script({
            "FAKE_LOCKED": "false",
            "FAKE_IDLE_NS": str(240 * 10**9),
            "USER_STATE_ACTIVE_IDLE_SEC": "300",
        })
        self.assertEqual(r.returncode, 0)

    def test_explain_prints_verdict(self):
        r = self.run_script(
            {"FAKE_LOCKED": "false", "FAKE_IDLE_NS": str(30 * 10**9)},
            args=("--explain",),
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("verdict=active", r.stdout)
        self.assertIn("locked=false", r.stdout)
        self.assertIn("idle_sec=30", r.stdout)


if __name__ == "__main__":
    unittest.main()
