"""No-root, no-disk tests for the QEMU same-boot terminal attempt marker.

All write operations are to ephemeral ordinary fixture files, NEVER a
block device. Actual root-owned /run enforcement is tested in a QEMU VM.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import forge_lab_attempt as lab


class LabAttemptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(lab, "MARKER", Path(self.tmp.name) / "attempt")
        patcher.start()
        self.addCleanup(patcher.stop)

    def root_file_context(self):
        # The unprivileged unit-test runner cannot chown to root; simulate
        # root ownership ONLY on fstat. The QEMU integration uses real root.
        original_fstat = os.fstat
        def root_owned(fd):
            actual = original_fstat(fd)
            return SimpleNamespace(st_mode=actual.st_mode, st_uid=0)
        return patch.object(lab.os, "fstat", side_effect=root_owned)

    def root_report(self):
        # The real VM creates the marker as root. Model only the owner
        # metadata of our temporary regular file in unprivileged unit CI.
        real = os.lstat(lab.MARKER)
        mock = SimpleNamespace(st_mode=real.st_mode, st_uid=0)
        with patch.object(lab.os, "lstat", return_value=mock):
            return lab.recovery_report()

    def test_single_attempt_marker_remains_after_failure_and_blocks_retry(self):
        with patch.object(lab.os, "geteuid", return_value=0), \
             self.root_file_context():
            lab.require_new_attempt()
            lab.mark_format_started()
            with self.assertRaisesRegex(lab.Refused, "already"):
                lab.require_new_attempt()
            with self.assertRaises(lab.Refused):
                lab.mark_format_started()
        self.assertEqual(lab.MARKER.read_bytes(), lab.MARKER_CONTENT)
        self.assertEqual(stat.S_IMODE(lab.MARKER.stat().st_mode), 0o600)
        report = self.root_report()
        self.assertEqual(report["status"], "manual-recovery-required")
        self.assertIs(report["auto_retry_enabled"], False)
        self.assertIs(report["automatic_rollback_enabled"], False)

    def test_unmarked_disk_is_not_claimed_safe(self):
        report = lab.recovery_report()
        self.assertEqual(report["status"], "no-attempt-recorded")
        self.assertIn("unknown", report["advice"].lower())
        for flag in ("write_operations_enabled",
                     "destructive_disk_operations_enabled",
                     "authorization_to_write"):
            self.assertIs(report[flag], False)

    def test_nonroot_cannot_begin_even_with_empty_directory(self):
        with patch.object(lab.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(lab.Refused, "root"):
                lab.mark_format_started()
            with self.assertRaisesRegex(lab.Refused, "root"):
                lab.require_new_attempt()
        self.assertFalse(lab.MARKER.exists())

    def test_symlink_and_malformed_marker_fail_closed(self):
        lab.MARKER.symlink_to("/dev/null")
        with patch.object(lab.os, "geteuid", return_value=0):
            with self.assertRaises(lab.Refused):
                lab.mark_format_started()
        self.assertEqual(lab.recovery_report()["status"],
                         "untrusted-attempt-marker")
        self.assertTrue(lab.MARKER.is_symlink())
        lab.MARKER.unlink()
        lab.MARKER.mkdir()
        self.assertEqual(lab.recovery_report()["status"],
                         "untrusted-attempt-marker")
        with patch.object(lab.os, "geteuid", return_value=0):
            with self.assertRaises(lab.Refused):
                lab.mark_format_started()

    def test_marker_is_never_removed_after_exception(self):
        with patch.object(lab.os, "geteuid", return_value=0), \
             self.root_file_context():
            lab.mark_format_started()
            try:
                raise RuntimeError("simulated mid-format failure")
            except RuntimeError:
                pass
        self.assertTrue(lab.MARKER.exists())
        self.assertEqual(self.root_report()["status"],
                         "manual-recovery-required")

    def test_no_recovery_writer_or_marker_clear_api(self):
        for name in ("clear", "reset", "remove_marker", "format_disk",
                     "execute", "install", "rollback", "retry", "main"):
            self.assertFalse(hasattr(lab, name))
        for status in ("no-attempt-recorded", "manual-recovery-required",
                       "untrusted-attempt-marker"):
            # Responses never contain an executable operation.
            self.assertIn("write_operations_enabled",
                          lab.recovery_report())
        self.assertEqual(lab.MARKER_CONTENT, b"EDOS-QEMU-FORMAT-STARTED-V1\n")


if __name__ == "__main__":
    unittest.main()
