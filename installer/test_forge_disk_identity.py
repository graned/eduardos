"""Read-only disk identity contract fixtures: no real block access."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

import forge_disk_identity as gate
import forge_installer as core

GIB = 1024**3
ID = "/dev/disk/by-id/wwn-0xfixture"
BOOT = "5cfa9edc-8a77-4bbf-89bc-4de50e8d6721"
SYSTEM = {"architecture": "x86_64", "uefi": True, "memory_bytes": 8*GIB,
          "sufficient_memory": True, "architecture_supported": True}
DISK = {"name": "vdb", "path": "/dev/vdb", "type": "disk",
        "size": 64*GIB, "model": "Virtio Fixture", "serial": "FIXTURE-123",
        "wwn": "0xabc123", "tran": "virtio", "maj:min": "252:16",
        "ro": False, "rm": False, "pttype": None, "fstype": None,
        "mountpoints": [None]}
DATA = {"blockdevices": [DISK]}
IDS = {"/dev/vdb": ID}


class DiskIdentityTests(unittest.TestCase):
    def capture(self, *, data=None, ids=None, boot=BOOT):
        with patch.object(core, "system_preflight", return_value=SYSTEM):
            return gate.capture(ID, data=DATA if data is None else data,
                                ids=IDS if ids is None else ids, current_boot_id=boot)

    def verify(self, review, *, data=None, ids=None, boot=BOOT):
        with patch.object(core, "system_preflight", return_value=SYSTEM):
            return gate.verify(review, data=DATA if data is None else data,
                               ids=IDS if ids is None else ids, current_boot_id=boot)

    def test_empty_disk_identity_is_eligible_but_read_only(self):
        review = self.capture()
        self.assertTrue(review["snapshot"]["eligible"])
        self.assertFalse(review["write_operations_enabled"])
        self.assertEqual(review["snapshot"]["stable_id"], ID)
        self.assertEqual(review["snapshot"]["device"]["serial"], "FIXTURE-123")
        self.assertTrue(self.verify(review)["verified"])

    def test_no_hardware_serial_or_wwn_is_blocked(self):
        data = {"blockdevices": [{**DISK, "serial": None, "wwn": None}]}
        review = self.capture(data=data)
        self.assertFalse(review["snapshot"]["eligible"])
        with self.assertRaises(gate.Refused):
            self.verify(review, data=data)

    def test_reject_changed_size_model_serial_wwn_path_and_devno(self):
        review = self.capture()
        for key, value in [
            ("size", 128*GIB), ("model", "Another Disk"), ("serial", "DIFFERENT"),
            ("wwn", "0xother"), ("path", "/dev/sdc"), ("maj:min", "8:32"),
        ]:
            with self.subTest(key=key):
                data = {"blockdevices": [{**DISK, key: value}]}
                with self.assertRaises(gate.Refused):
                    self.verify(review, data=data)

    def test_reject_changed_boot_session(self):
        review = self.capture()
        with self.assertRaisesRegex(gate.Refused, "changed"):
            self.verify(review, boot="9d7bca90-4ad8-4b9b-8120-d434a2ec76c9")

    def test_reject_partition_mount_swap_and_read_only(self):
        review = self.capture()
        cases = [
            {**DISK, "children": [
                {"path": "/dev/vdb1", "type": "part", "mountpoints": [None]}]},
            {**DISK, "children": [
                {"path": "/dev/vdb1", "type": "part", "mountpoints": ["/home"]}]},
            {**DISK, "children": [
                {"path": "/dev/vdb1", "type": "part", "fstype": "swap"}]},
            {**DISK, "ro": True},
            {**DISK, "pttype": "gpt"},
        ]
        for disk in cases:
            with self.subTest(disk=disk):
                data = {"blockdevices": [disk]}
                self.assertFalse(self.capture(data=data)["snapshot"]["eligible"])
                with self.assertRaises(gate.Refused):
                    self.verify(review, data=data)

    def test_reject_disappearing_or_ambiguous_identifier(self):
        review = self.capture()
        with self.assertRaises(gate.Refused):
            self.verify(review, ids={})
        with self.assertRaises(gate.Refused):
            self.verify(review, ids={"/dev/vdb": ID, "/dev/sdc": ID})

    def test_reject_modified_snapshot_hash(self):
        review = self.capture()
        tampered = copy.deepcopy(review)
        tampered["snapshot"]["device"]["serial"] = "FORGED"
        with self.assertRaisesRegex(gate.Refused, "fingerprint"):
            self.verify(tampered)

    def test_reject_forged_write_flag_and_missing_schema(self):
        review = self.capture()
        for key, val in [("write_operations_enabled", True), ("extra", "x")]:
            tampered = copy.deepcopy(review)
            tampered[key] = val
            with self.assertRaises(gate.Refused):
                self.verify(tampered)
        tampered = copy.deepcopy(review)
        tampered["snapshot"]["schema"] = "other"
        tampered["sha256"] = gate.fingerprint(tampered["snapshot"])
        with self.assertRaises(gate.Refused):
            self.verify(tampered)

    def test_reject_invalid_stable_id(self):
        for bad in ("/dev/vdb", "/dev/disk/by-id/../vdb", "file:///dev/vdb", ""):
            with self.subTest(bad=bad), self.assertRaises(gate.Refused):
                self.capture(ids={"/dev/vdb": bad})

    def test_no_snapshot_authorizes_installation(self):
        review = self.capture()
        self.assertNotIn("execute", review)
        self.assertNotIn("install", review)
        self.assertEqual(self.verify(review)["write_operations_enabled"], False)


if __name__ == "__main__":
    unittest.main()
