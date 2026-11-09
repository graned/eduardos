"""No-disk subprocess interruption tests for the disposable QEMU executor."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import forge_lab_child as child


class QemuChildTests(unittest.TestCase):
    def test_nonzero_exit_is_not_retried(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            child.run_child([sys.executable, "-c", "raise SystemExit(49)"])
        self.assertEqual(error.exception.returncode, 49)

    def test_success_and_invalid_argv(self):
        child.run_child([sys.executable, "-c", "pass"])
        for invalid in ([], [""], ["echo", "ok", ""]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                child.run_child(invalid)

    def test_sigterm_ends_supervisor_and_running_formatter(self):
        with tempfile.TemporaryDirectory() as temp:
            ready = Path(temp) / "ready"
            pidfile = Path(temp) / "pid"
            # A harmless worker stands in for Disko. No disks are opened.
            worker = (
                "import os,time;from pathlib import Path;"
                f"Path({str(pidfile)!r}).write_text(str(os.getpid()));"
                f"Path({str(ready)!r}).touch();time.sleep(60)"
            )
            launcher = (
                "import sys;"
                f"sys.path.insert(0,{str(Path(__file__).parent)!r});"
                "import forge_lab_child as c;"
                f"c.run_child([{sys.executable!r},'-c',{worker!r}])"
            )
            parent = subprocess.Popen([sys.executable, "-c", launcher],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and parent.poll() is None:
                    if time.monotonic() > deadline:
                        self.fail("Harmless child did not start")
                    time.sleep(0.05)
                self.assertTrue(ready.exists(), "Supervisor exited before worker started")
                worker_pid = int(pidfile.read_text())
                parent.send_signal(signal.SIGTERM)
                self.assertNotEqual(parent.wait(timeout=10), 0)

                def still_running(pid):
                    try:
                        stat = Path(f"/proc/{pid}/stat").read_text()
                    except FileNotFoundError:
                        return False
                    # A transient zombie has already stopped executing.
                    return stat.rsplit(") ", 1)[1][0] not in ("Z", "X")

                deadline = time.monotonic() + 5
                while still_running(worker_pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(still_running(worker_pid),
                                 "Formatter survived supervisor cancellation")
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
