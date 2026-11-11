"""Fail-closed preformat disk re-attestation; all tests use mocked block data.

No root privileges, real block-device opens, formatting or mounts.
"""
import os
import stat
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_backend as backend
import forge_privileged_guard as guard

DEVICE = "/dev/sdb"
STABLE = "/dev/disk/by-id/wwn-0x1234"
FIELDS = {"size": 64 * (1024 ** 3), "model": "Test disk",
          "serial": "serial", "wwn": "wwn", "tran": "virtio",
          "maj:min": "8:16", "ro": False, "rm": False}


def session():
    return backend.HeldTarget(
        fd=81,
        review={"snapshot": {"stable_id": STABLE, "boot_id": "boot-1",
                            "device": {"path": DEVICE, **FIELDS}}},
        username="testpilot", hostname="edos-test",
        devno="8:16", deadline=time.monotonic() + 60,
    )


class PreFormatBoundaryTests(unittest.TestCase):
    def test_read_only_double_recheck_and_no_write_authority(self):
        held = session()
        with mock.patch.object(backend, "_root_required"), \
             mock.patch.object(backend.identity, "probe", return_value={"blockdevices": []}) as probe, \
             mock.patch.object(backend.identity, "verify", return_value={
                 "verified": True, "stable_id": STABLE, "write_operations_enabled": False,
             }) as verify, \
             mock.patch.object(backend.guard, "guard_topology", return_value={
                 "target_path": DEVICE, "target_devno": "8:16",
                 "write_operations_enabled": False,
             }) as topology, \
             mock.patch.object(backend.Path, "read_text", side_effect=["mountinfo", "swaps"]), \
             mock.patch.object(backend.live, "sysfs_loop_backings", return_value={}), \
             mock.patch.object(held, "_fresh_device") as fresh:
            report = held.reattest_preformat()
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(fresh.call_count, 2)
        verify.assert_called_once()
        topology.assert_called_once()
        self.assertFalse(report["write_operations_enabled"])
        self.assertFalse(report["authorization_to_write"])
        self.assertFalse(report["destructive_disk_operations_enabled"])

    def test_new_mount_or_swap_refuses(self):
        held = session()
        with mock.patch.object(backend, "_root_required"), \
             mock.patch.object(backend.identity, "probe", return_value={}), \
             mock.patch.object(backend.identity, "verify", return_value={
                 "verified": True, "stable_id": STABLE, "write_operations_enabled": False,
             }), \
             mock.patch.object(backend.guard, "guard_topology",
                               side_effect=guard.Refused("new target mount")), \
             mock.patch.object(backend.Path, "read_text", side_effect=["mountinfo", "swaps"]), \
             mock.patch.object(backend.live, "sysfs_loop_backings", return_value={}), \
             mock.patch.object(held, "_fresh_device") as fresh:
            with self.assertRaises(guard.Refused):
                held.reattest_preformat()
        fresh.assert_called_once()

    def test_identity_or_boot_changed_refuses(self):
        held = session()
        with mock.patch.object(backend, "_root_required"), \
             mock.patch.object(backend.identity, "probe", return_value={}), \
             mock.patch.object(backend.identity, "verify",
                               side_effect=backend.identity.Refused("changed boot")), \
             mock.patch.object(held, "_fresh_device"):
            with self.assertRaises(backend.identity.Refused):
                held.reattest_preformat()

    def test_hotplug_during_topology_scan_refuses(self):
        held = session()
        with mock.patch.object(backend, "_root_required"), \
             mock.patch.object(backend.identity, "probe", return_value={}), \
             mock.patch.object(backend.identity, "verify", return_value={
                 "verified": True, "stable_id": STABLE, "write_operations_enabled": False,
             }), \
             mock.patch.object(backend.guard, "guard_topology", return_value={
                 "target_path": DEVICE, "target_devno": "8:16",
                 "write_operations_enabled": False,
             }), \
             mock.patch.object(backend.Path, "read_text", side_effect=["mountinfo", "swaps"]), \
             mock.patch.object(backend.live, "sysfs_loop_backings", return_value={}), \
             mock.patch.object(held, "_fresh_device",
                               side_effect=[None, backend.Refused("hotplug")]) as fresh:
            with self.assertRaisesRegex(backend.Refused, "hotplug"):
                held.reattest_preformat()
        self.assertEqual(fresh.call_count, 2)

    def test_held_block_alias_change_refuses(self):
        held = session()
        meta = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600,
                               st_rdev=os.makedev(8, 16))
        replaced = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600,
                                   st_rdev=os.makedev(8, 32))
        with mock.patch.object(backend, "_root_required"), \
             mock.patch.object(backend.identity, "boot_id", return_value="boot-1"), \
             mock.patch.object(backend.identity, "flat_disks",
                               return_value={DEVICE: dict(FIELDS)}), \
             mock.patch.object(backend.os, "fstat", return_value=meta), \
             mock.patch.object(backend.os, "stat", return_value=replaced):
            with self.assertRaisesRegex(backend.Refused, "Stable device path"):
                held._fresh_device({})

    def test_consumed_target_refuses(self):
        held = session()
        held.used = True
        with self.assertRaisesRegex(backend.Refused, "consumed"):
            held.reattest_preformat()


if __name__ == "__main__":
    unittest.main()
