"""Read-only auditor tests using an entirely synthetic lsblk/mountinfo fixture."""
import contextlib
import io
import json
import os
import stat
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import forge_mount_audit as auditor
from test_forge_backend import DATA, MOUNTS, entry, MAPPER


def block_meta(devno="8:16", *, block=True):
    major, minor = map(int, devno.split(":"))
    return SimpleNamespace(
        st_mode=(stat.S_IFBLK if block else stat.S_IFREG) | 0o600,
        st_rdev=os.makedev(major, minor),
    )


class AuditTests(unittest.TestCase):
    def test_already_mounted_encrypted_target_produces_read_only_evidence(self):
        with patch.object(auditor.os, "stat", return_value=block_meta()):
            result = auditor.audit("/dev/vdb", lsblk_data=DATA, mountinfo=MOUNTS)
        self.assertEqual(result["status"], "verified-already-mounted-encrypted-target")
        self.assertEqual(result["target_devno"], "8:16")
        self.assertEqual(len(result["mountpoints"]), 6)
        self.assertIs(result["destructive_disk_operations_enabled"], False)
        self.assertIs(result["credential_writes_enabled"], False)
        self.assertNotIn("password", json.dumps(result))

    def test_refuse_non_block_or_changed_kernel_device(self):
        for meta in (block_meta(block=False), block_meta("8:32")):
            with self.subTest(meta=meta), patch.object(
                auditor.os, "stat", return_value=meta
            ), self.assertRaises(auditor.Refused):
                auditor.audit("/dev/vdb", lsblk_data=DATA, mountinfo=MOUNTS)

    def test_refuse_missing_or_wrong_target_disk(self):
        for path in ("/dev/vda", "/dev/vdb1", "/dev/../vdb", "/tmp/vdb", "vdb", "/dev//../vdb"):
            with self.subTest(path=path), self.assertRaises(auditor.Refused):
                auditor.audit(path, lsblk_data=DATA, mountinfo=MOUNTS)

    def test_refuse_missing_encrypted_mountpoint(self):
        wrong = MOUNTS.replace(
            entry("/mnt/persist", "0:55", "/@persist", "btrfs", MAPPER),
            "",
        )
        with patch.object(auditor.os, "stat", return_value=block_meta()), \
             self.assertRaisesRegex(auditor.backend.Refused, "mountpoints"):
            auditor.audit("/dev/vdb", lsblk_data=DATA, mountinfo=wrong)

    def test_refuse_efi_mounted_from_another_partition(self):
        wrong = MOUNTS.replace(
            entry("/mnt/boot", "8:17", "/", "vfat", "/dev/vdb1"),
            entry("/mnt/boot", "8:18", "/", "vfat", "/dev/vdb2"),
        )
        with patch.object(auditor.os, "stat", return_value=block_meta()), \
             self.assertRaises(auditor.backend.Refused):
            auditor.audit("/dev/vdb", lsblk_data=DATA, mountinfo=wrong)

    def test_cli_reports_failure_without_exposing_traceback(self):
        with patch.object(auditor, "audit", side_effect=auditor.Refused("mount not verified")), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(auditor.main(["--disk", "/dev/vdb"]), 2)
        self.assertIn("REFUSED:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_no_destructive_api_or_credential_writer(self):
        for name in ("format_disk", "partition", "install", "wipe", "stage_account_hash"):
            self.assertFalse(hasattr(auditor, name))


if __name__ == "__main__":
    unittest.main()
