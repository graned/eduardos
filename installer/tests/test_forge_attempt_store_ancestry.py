"""Pure mount-ancestry fixtures: no block access, root, or disk writes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge_attempt_store_ancestry import Refused, attest_separate_backing

STORE = "/var/lib/edos-attempts"
MOUNT = f"99 20 8:17 / {STORE} rw,relatime - ext4 /dev/sdb1 rw\n"
DISKS = {"blockdevices": [
    {"path": "/dev/sda", "type": "disk", "maj:min": "8:0", "ro": False, "rm": False},
    {"path": "/dev/sdb", "type": "disk", "maj:min": "8:16", "ro": False, "rm": False,
     "children": [{"path": "/dev/sdb1", "type": "part", "maj:min": "8:17",
                   "ro": False, "rm": False}]},
]}


class StoreAncestryTests(unittest.TestCase):
    def check(self, **overrides):
        return attest_separate_backing(**{
            "mountpoint": STORE, "mountinfo": MOUNT,
            "block_inventory": DISKS, "target_devno": "8:0",
            **overrides,
        })

    def test_separate_disk_is_candidate_not_proof(self):
        report = self.check()
        self.assertEqual(report["store_disk_devno"], "8:16")
        self.assertEqual(report["install_target_devno"], "8:0")
        self.assertFalse(report["durability_proven"])
        self.assertFalse(report["authorization_to_write"])
        self.assertFalse(report["write_operations_enabled"])

    def test_target_is_same_disk_as_attempt_store(self):
        with self.assertRaises(Refused):
            self.check(target_devno="8:16")

    def test_unmapped_or_missing_store_devices_fail_closed(self):
        for mount in (MOUNT.replace("8:17", "253:99"), MOUNT.replace("ext4", "tmpfs"),
                      MOUNT.replace("/dev/sdb1", "tmpfs"), MOUNT + MOUNT):
            with self.subTest(mount=mount), self.assertRaises(Refused):
                self.check(mountinfo=mount)

    def test_removable_or_read_only_ancestor_rejected(self):
        for flag in ("ro", "rm"):
            inventory = {"blockdevices": [DISKS["blockdevices"][0],
                {**DISKS["blockdevices"][1], flag: True}]}
            with self.subTest(flag=flag), self.assertRaises(Refused):
                self.check(block_inventory=inventory)

    def test_invalid_target_and_incomplete_topology_rejected(self):
        for bad in ("", "8:17", "foo", "12:3\n"):
            with self.subTest(target=bad), self.assertRaises(Refused):
                self.check(target_devno=bad)
        with self.assertRaises(Refused):
            self.check(block_inventory={"blockdevices": []})

    def test_forged_partition_crossing_multiple_physical_disks_is_rejected(self):
        # An ambiguous storage topology is never enough to grant permission.
        inventory = {"blockdevices": [
            {"path": "/dev/sda", "type": "disk", "maj:min": "8:0"},
            {"path": "/dev/sdb", "type": "disk", "maj:min": "8:16",
             "children": [{"path": "/dev/md0", "type": "raid1", "maj:min": "9:0",
                           "children": [{"path": "/dev/sdb1", "type": "part", "maj:min": "8:17"}]}]},
            {"path": "/dev/sdc", "type": "disk", "maj:min": "8:32",
             "children": [{"path": "/dev/md0", "type": "raid1", "maj:min": "9:0",
                           "children": [{"path": "/dev/sdb1", "type": "part", "maj:min": "8:17"}]}]},
        ]}
        with self.assertRaises(Refused):
            self.check(block_inventory=inventory)


if __name__ == "__main__":
    unittest.main()
