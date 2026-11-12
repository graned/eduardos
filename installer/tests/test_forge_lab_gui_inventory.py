"""Regressions for the ONLY exception to Forge's production disk minimum.

No VM, root, real disks or executor calls. The separate QEMU lab mode
may expose the exact disposable /dev/vda fixture; all other blockers
and every production preview remain unchanged.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_installer as core
import forge_gui
import forge_lab_gui_session as lab

ALIAS = "/dev/disk/by-id/virtio-root"


def disk(*reasons):
    return core.Disk(
        path="/dev/vda", model="Disposable QEMU",
        size=12 * 1024**3, transport="virtio", by_id=ALIAS,
        eligible=not bool(reasons), reasons=tuple(reasons),
    )


SYSTEM = {
    "architecture": "x86_64",
    "architecture_supported": True,
    "uefi": False,
    "memory_bytes": 3900 * 1024**2,
    "sufficient_memory": False,
}


class QemuTargetPreviewTests(unittest.TestCase):
    def session(self, candidate):
        obj = object.__new__(lab.LabInstallSession)
        with mock.patch.object(obj, "_verify_vm"), \
             mock.patch.object(lab.core, "run_lsblk", return_value={}), \
             mock.patch.object(lab.core, "stable_ids", return_value={}), \
             mock.patch.object(lab.core, "disk_inventory", return_value=[candidate]), \
             mock.patch.object(lab.core, "system_preflight", return_value=SYSTEM):
            return obj.inventory(), obj.preview(ALIAS)

    def test_disposable_twelve_gib_disk_is_selectable_only_in_lab(self):
        inventory, plan = self.session(disk("Smaller than the 32 GiB minimum"))
        self.assertEqual(len(inventory["disks"]), 1)
        self.assertTrue(inventory["disks"][0]["eligible"])
        self.assertEqual(plan["status"], "ready-for-review")
        self.assertEqual(plan["blockers"], [])
        self.assertTrue(plan["lab_only"])
        self.assertIs(plan["would_write_to_disk"], False)
        self.assertIs(inventory["write_operations_enabled"], False)
        self.assertIs(SYSTEM["uefi"], False)  # never mutate source of truth
        self.assertIs(SYSTEM["sufficient_memory"], False)

    def test_mounted_or_read_only_disk_stays_blocked(self):
        for reasons in (
            ("Smaller than the 32 GiB minimum", "Disk or a descendant has a mounted filesystem"),
            ("Read-only device",),
            ("No stable /dev/disk/by-id identifier",),
        ):
            with self.subTest(reasons=reasons), \
                 self.assertRaises(lab.Refused):
                self.session(disk(*reasons))

    def test_wrong_stable_alias_stays_blocked(self):
        wrong = core.Disk("/dev/vda", "QEMU", 12 * 1024**3, "virtio",
                          "/dev/disk/by-id/virtio-wrong", False,
                          ("Smaller than the 32 GiB minimum",))
        with self.assertRaises(lab.Refused):
            self.session(wrong)

    def test_other_target_cannot_be_previewed(self):
        obj = object.__new__(lab.LabInstallSession)
        with self.assertRaises(lab.Refused):
            obj.preview("/dev/vdb")

    def test_regular_production_minimum_never_changes(self):
        self.assertEqual(core.MIN_DISK_BYTES, 32 * 1024**3)
        candidate = disk("Smaller than the 32 GiB minimum")
        result = core.preview(candidate, {**SYSTEM, "uefi": True, "sufficient_memory": True})
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(candidate.eligible)
        self.assertEqual(forge_gui.install_capabilities()["installation_available"], False)


if __name__ == "__main__":
    unittest.main()
