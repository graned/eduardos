"""Fixture-driven safety tests; never require real disks or privileged access."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import forge_installer as fi

GIB = 1024 ** 3
DISK = {
    "name": "vdb", "path": "/dev/vdb", "type": "disk", "size": 64 * GIB,
    "model": "Disposable Virtual Disk", "tran": "virtio", "ro": False, "rm": False,
    "mountpoints": [None], "fstype": None,
}
ID = "/dev/disk/by-id/virtio-disposable-fixture"
SYSTEM = {"architecture": "x86_64", "uefi": True, "memory_bytes": 8 * GIB,
          "sufficient_memory": True, "architecture_supported": True}


class InstallerPreflightTests(unittest.TestCase):
    def discover(self, disk=None, ids=None):
        return fi.disk_inventory({"blockdevices": [disk or DISK]}, ids if ids is not None else {"/dev/vdb": ID})[0]

    def test_eligible_empty_disk_and_preview_cannot_write(self):
        disk = self.discover()
        self.assertTrue(disk.eligible)
        self.assertEqual(disk.by_id, ID)
        plan = fi.preview(disk, SYSTEM)
        self.assertEqual(plan["status"], "ready-for-review")
        self.assertFalse(plan["would_write_to_disk"])
        self.assertEqual(len(plan["planned_layout"]), 3)

    def test_blocks_disk_with_mounted_child(self):
        disk = {**DISK, "children": [
            {"path": "/dev/vdb1", "type": "part", "mountpoints": ["/home"]}
        ]}
        found = self.discover(disk)
        self.assertFalse(found.eligible)
        self.assertIn("mounted", " ".join(found.reasons))

    def test_blocks_disk_with_swap(self):
        disk = {**DISK, "children": [
            {"path": "/dev/vdb1", "type": "part", "mountpoints": [None], "fstype": "swap"}
        ]}
        self.assertFalse(self.discover(disk).eligible)

    def test_blocks_active_encrypted_stack(self):
        disk = {**DISK, "children": [
            {"path": "/dev/vdb2", "type": "part", "children": [
                {"path": "/dev/mapper/crypt", "type": "crypt"}]}
        ]}
        self.assertFalse(self.discover(disk).eligible)

    def test_blocks_small_removable_read_only_and_missing_id(self):
        for modification in ({"size": 8 * GIB}, {"rm": True}, {"ro": True}):
            with self.subTest(modification=modification):
                self.assertFalse(self.discover({**DISK, **modification}).eligible)
        self.assertFalse(self.discover(ids={}).eligible)

    def test_system_requirements_block(self):
        disk = self.discover()
        for modification in ({"uefi": False}, {"sufficient_memory": False},
                             {"architecture_supported": False}):
            with self.subTest(modification=modification):
                plan = fi.preview(disk, {**SYSTEM, **modification})
                self.assertEqual(plan["status"], "blocked")
                self.assertFalse(plan["would_write_to_disk"])

    def test_selection_only_accepts_discovered_stable_id(self):
        with patch.object(fi, "system_preflight", return_value=SYSTEM), \
             patch.object(fi, "run_lsblk", return_value={"blockdevices": [DISK]}), \
             patch.object(fi, "stable_ids", return_value={"/dev/vdb": ID}):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(fi.main(["--disk", "/dev/vdb"]), 2)
                self.assertEqual(fi.main(["--disk", "/dev/disk/by-id/evil"]), 2)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(fi.main(["--disk", ID]), 0)
            self.assertEqual(json.loads(output.getvalue())["mode"], "dry-run-only")

    def test_machine_json_never_invokes_installation(self):
        with patch.object(fi, "system_preflight", return_value=SYSTEM), \
             patch.object(fi, "run_lsblk", return_value={"blockdevices": [DISK]}), \
             patch.object(fi, "stable_ids", return_value={"/dev/vdb": ID}):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(fi.main(["--json"]), 0)
            self.assertFalse(json.loads(output.getvalue())["write_operations_enabled"])

    def test_unknown_device_and_empty_selection(self):
        self.assertEqual(fi.preview(None, SYSTEM)["status"], "blocked")
        with patch("builtins.input", return_value=""), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fi.interactive([self.discover()], SYSTEM), 0)


if __name__ == "__main__":
    unittest.main()
