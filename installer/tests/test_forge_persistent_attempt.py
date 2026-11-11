"""Non-destructive persistent-attempt refusal tests."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge_persistent_attempt import Refused, begin_attempt, inspect_attempt, marker_name

DISK = "/dev/disk/by-id/wwn-0x123abc"


class AttemptRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "attempts"
        self.root.mkdir(mode=0o700)
        self.addCleanup(self.tmp.cleanup)

    def test_marker_survives_new_function_calls_and_refuses_second_attempt(self):
        self.assertEqual(inspect_attempt(self.root, DISK), "none")
        name = begin_attempt(self.root, DISK)
        self.assertEqual(inspect_attempt(self.root, DISK), "reserved-no-auto-retry")
        self.assertEqual((self.root / name).stat().st_mode & 0o777, 0o600)
        with self.assertRaises(Refused):
            begin_attempt(self.root, DISK)

    def test_distinct_devices_use_distinct_nonsecret_hashes(self):
        first = begin_attempt(self.root, DISK)
        second = begin_attempt(self.root, "/dev/disk/by-id/wwn-0x456def")
        self.assertNotEqual(first, second)
        self.assertNotIn("wwn", first)

    def test_partial_marker_requires_manual_recovery(self):
        (self.root / marker_name(DISK)).write_bytes(b"EDOS_ATTEMPT_V1\n")
        with self.assertRaisesRegex(Refused, "manual recovery"):
            inspect_attempt(self.root, DISK)
        with self.assertRaises(Refused):
            begin_attempt(self.root, DISK)

    def test_symlink_and_world_readable_directory_refused(self):
        alias = Path(self.tmp.name) / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(Refused):
            begin_attempt(alias, DISK)
        self.root.chmod(0o755)
        with self.assertRaises(Refused):
            begin_attempt(self.root, DISK)

    def test_bad_identifier_refused(self):
        for candidate in ("/dev/sda", "/dev/disk/by-id/../sda",
                          "/dev/disk/by-id/a b", "", "anything"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(Refused):
                    marker_name(candidate)

    def test_existing_symlink_record_refuses(self):
        target = Path(self.tmp.name) / "sentinel"
        target.write_text("unchanged")
        (self.root / marker_name(DISK)).symlink_to(target)
        with self.assertRaises(Refused):
            begin_attempt(self.root, DISK)
        with self.assertRaises(Refused):
            inspect_attempt(self.root, DISK)
        self.assertEqual(target.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
