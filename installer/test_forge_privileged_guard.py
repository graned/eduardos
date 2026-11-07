"""Synthetic block topology tests. No root, disks, or destructive commands."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import forge_privileged_guard as guard

GIB = 1024 ** 3
REVIEW = {
    "snapshot": {
        "device": {"path": "/dev/sdb"},
        "stable_id": "/dev/disk/by-id/wwn-blank-target",
    },
    "sha256": "a" * 64,
    "write_operations_enabled": False,
}
SWAPS_EMPTY = "Filename\tType\tSize\tUsed\tPriority\n"
ROOT_MOUNTS = (
    "21 1 253:0 / / rw,relatime - btrfs /dev/mapper/root rw\n"
    "22 21 8:1 / /boot rw,relatime - vfat /dev/sda1 rw\n"
)


def physical(name, devno, children=None):
    return {
        "name": name, "path": "/dev/" + name, "maj:min": devno,
        "type": "disk", "size": 64 * GIB,
        "ro": False, "rm": False, "mountpoints": [None],
        "children": children or [],
    }


def block(name, devno, kind="part", children=None, mounted=None):
    return {
        "name": name, "path": "/dev/" + name, "maj:min": devno,
        "type": kind, "mountpoints": [mounted],
        "children": children or [],
    }


BOOT = physical("sda", "8:0", [
    block("sda1", "8:1", mounted="/boot"),
    block("sda2", "8:2", children=[
        block("dm-0", "253:0", "crypt", mounted="/")
    ]),
])
EMPTY = physical("sdb", "8:16")
DATA = {"blockdevices": [BOOT, EMPTY]}


class PrivilegedGuardTests(unittest.TestCase):
    def test_blank_other_disk_passes_only_read_only(self):
        result = guard.guard_topology("/dev/sdb", DATA, ROOT_MOUNTS, SWAPS_EMPTY)
        self.assertEqual(result["target_devno"], "8:16")
        self.assertFalse(result["write_operations_enabled"])
        self.assertIn("8:0", result["protected_devices"])
        self.assertIn("253:0", result["protected_devices"])

    def test_encrypted_root_and_boot_parent_are_protected(self):
        for path in ("/dev/sda", "/dev/sda1"):
            with self.subTest(path=path):
                with self.assertRaises(guard.Refused):
                    guard.guard_topology(path, DATA, ROOT_MOUNTS, SWAPS_EMPTY)

    def test_raid_multi_parent_blocks_both_physical_disks(self):
        md = block("md0", "9:0", "raid1", mounted="/")
        sources = {"blockdevices": [
            physical("sda", "8:0", [block("sda1", "8:1", children=[md])]),
            physical("sdb", "8:16", [block("sdb1", "8:17", children=[md])]),
            physical("sdc", "8:32"),
        ]}
        root = "21 1 9:0 / / rw,relatime - ext4 /dev/md0 rw\n"
        for path in ("/dev/sda", "/dev/sdb"):
            with self.subTest(path=path), self.assertRaises(guard.Refused):
                guard.guard_topology(path, sources, root, SWAPS_EMPTY)
        self.assertEqual(guard.guard_topology("/dev/sdc", sources, root, SWAPS_EMPTY)["target_devno"],
                         "8:32")

    def test_unknown_overlay_root_is_rejected(self):
        mount = "20 1 0:42 / / rw,relatime - overlay overlay rw\n"
        with self.assertRaisesRegex(guard.Refused, "critical mount"):
            guard.guard_topology("/dev/sdb", DATA, mount, SWAPS_EMPTY)

    def test_missing_root_mount_is_rejected(self):
        with self.assertRaisesRegex(guard.Refused, "Root filesystem"):
            guard.guard_topology("/dev/sdb", DATA,
                                 "21 1 8:1 / /boot rw - vfat /dev/sda1 rw\n", SWAPS_EMPTY)

    def test_protect_swap_even_when_not_mounted(self):
        swap_disk = physical("sdb", "8:16", [block("sdb1", "8:17")])
        data = {"blockdevices": [BOOT, swap_disk]}
        swaps = SWAPS_EMPTY + "/dev/sdb1 partition 8192 0 -2\n"
        with self.assertRaisesRegex(guard.Refused, "active swap"):
            guard.guard_topology("/dev/sdb", data, ROOT_MOUNTS, swaps)

    def test_unknown_swapfile_blocks_every_candidate(self):
        swaps = SWAPS_EMPTY + "/swapfile file 8192 0 -2\n"
        with self.assertRaisesRegex(guard.Refused, "Active swap source"):
            guard.guard_topology("/dev/sdb", DATA, ROOT_MOUNTS, swaps)

    def test_mounted_noncritical_volume_still_protects_disk(self):
        data = {"blockdevices": [BOOT, physical("sdb", "8:16", [
            block("sdb1", "8:17", mounted="/data")
        ])]}
        with self.assertRaises(guard.Refused):
            guard.guard_topology("/dev/sdb", data, ROOT_MOUNTS, SWAPS_EMPTY)

    def test_fail_closed_incomplete_or_conflicting_graph(self):
        with self.assertRaises(guard.Refused):
            guard.guard_topology("/dev/sdb", {"blockdevices": []},
                                 ROOT_MOUNTS, SWAPS_EMPTY)
        bad = {"blockdevices": [
            physical("sda", "8:0"),
            physical("sdb", "8:0"),
        ]}
        with self.assertRaises(guard.Refused):
            guard.block_graph(bad)

    def test_unprivileged_process_never_verifies_or_proceeds(self):
        with patch.object(guard.identity, "verify") as verify:
            with self.assertRaisesRegex(guard.Refused, "Root privileges"):
                guard.privileged_preflight(REVIEW, euid=1000)
            verify.assert_not_called()

    def test_privileged_preflight_revalidates_twice_and_cannot_write(self):
        with patch.object(guard.identity, "verify", return_value={"verified": True}) as verify:
            result = guard.privileged_preflight(
                REVIEW, euid=0, lsblk_data=DATA,
                mountinfo=ROOT_MOUNTS, swaps=SWAPS_EMPTY)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(result["status"], "preflight-passed")
        self.assertFalse(result["write_operations_enabled"])
        self.assertNotIn("execute", result)
        self.assertFalse(hasattr(guard, "install"))

    def test_identity_revalidation_failure_is_final(self):
        with patch.object(guard.identity, "verify",
                          side_effect=guard.identity.Refused("stale")):
            with self.assertRaises(guard.identity.Refused):
                guard.privileged_preflight(REVIEW, euid=0,
                                           lsblk_data=DATA,
                                           mountinfo=ROOT_MOUNTS,
                                           swaps=SWAPS_EMPTY)

    def test_review_file_symlink_and_oversize_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            normal = Path(directory) / "review.json"
            normal.write_text(json.dumps(REVIEW))
            self.assertEqual(guard.load_review(str(normal)), REVIEW)
            alias = Path(directory) / "alias"
            alias.symlink_to(normal)
            with self.assertRaises(OSError):
                guard.load_review(str(alias))
            normal.write_text("x" * (guard.MAX_REVIEW_SIZE + 1))
            with self.assertRaises(guard.Refused):
                guard.load_review(str(normal))


if __name__ == "__main__":
    unittest.main()
