"""Synthetic live ISO provenance tests: no mounts, root, devices or disk writes."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import forge_live_media as media
import forge_privileged_guard as guard

GIB = 1024 ** 3
SWAPS = "Filename\tType\tSize\tUsed\tPriority\n"


def node(name, dev, kind="disk", children=None, mount=None):
    return {
        "name": name, "path": "/dev/" + name, "maj:min": dev,
        "type": kind, "size": 64 * GIB, "ro": False, "rm": False,
        "mountpoints": [mount], "children": children or [],
    }


DATA = {"blockdevices": [
    node("sda", "8:0", children=[node("sda1", "8:1", "part", mount="/iso")]),
    node("sdb", "8:16"),
    node("loop0", "7:0", "loop", mount="/nix/.ro-store"),
]}
ISO = (
    "20 1 0:42 / / rw,relatime - overlay overlay "
    "rw,lowerdir=/nix/.ro-store,upperdir=/run/overlay/upper,workdir=/run/overlay/work\n"
    "21 20 0:22 / /run rw,relatime - tmpfs tmpfs rw\n"
    "22 20 8:1 / /iso ro,relatime - iso9660 /dev/sda1 ro\n"
    "23 20 7:0 / /nix/.ro-store ro,relatime - squashfs /dev/loop0 ro\n"
)
LOOPS = {"7:0": "/iso/nix-store.squashfs"}


class LiveBootTests(unittest.TestCase):
    def assert_refused(self, mountinfo=ISO, loops=None, data=None):
        with self.assertRaises((guard.Refused, media.Refused)):
            guard.guard_topology("/dev/sdb", data or DATA, mountinfo,
                                 SWAPS, loop_backings=LOOPS if loops is None else loops)

    def test_proven_overlay_protects_iso_ancestors(self):
        good = guard.guard_topology("/dev/sdb", DATA, ISO, SWAPS, loop_backings=LOOPS)
        self.assertEqual(good["target_devno"], "8:16")
        self.assertFalse(good["write_operations_enabled"])
        self.assertEqual(good["live_media"]["source"], "overlay-squashfs-loop-iso9660")
        self.assertIn("8:0", good["protected_devices"])
        self.assertIn("8:1", good["protected_devices"])
        self.assertIn("7:0", good["protected_devices"])

    def test_refuse_target_that_booted_the_live_iso(self):
        with self.assertRaisesRegex(guard.Refused, "mounted filesystem"):
            guard.guard_topology("/dev/sda", DATA, ISO, SWAPS, loop_backings=LOOPS)

    def test_legacy_without_provenance_still_fails_closed(self):
        self.assert_refused(loops={})

    def test_reject_unknown_iso_source(self):
        self.assert_refused(mountinfo=ISO.replace("8:1 / /iso", "11:0 / /iso"))

    def test_reject_loop_missing_or_wrong_backing_file(self):
        self.assert_refused(loops={"7:0": "/unmounted/nix-store.squashfs"})
        self.assert_refused(loops={"7:0": "/run/nix-store.squashfs"})
        self.assert_refused(loops={"9:0": "/iso/nix-store.squashfs"})

    def test_reject_non_iso9660_or_non_squashfs_mount(self):
        self.assert_refused(mountinfo=ISO.replace("iso9660 /dev/sda1", "ext4 /dev/sda1"))
        self.assert_refused(mountinfo=ISO.replace("squashfs /dev/loop0", "ext4 /dev/loop0"))
        self.assert_refused(mountinfo=ISO.replace("/nix/.ro-store ro,relatime - squashfs",
                                                  "/nix/.ro-store ro,relatime - tmpfs"))

    def test_reject_persistent_overlay_upper_or_work(self):
        bad = ISO.replace("upperdir=/run/overlay/upper", "upperdir=/iso/upper")
        self.assert_refused(mountinfo=bad)
        bad = ISO.replace("workdir=/run/overlay/work", "workdir=/iso/work")
        self.assert_refused(mountinfo=bad)
        bad = ISO.replace(" - tmpfs tmpfs rw", " - ext4 /dev/sdc rw")
        self.assert_refused(mountinfo=bad)

    def test_reject_unverified_extra_lower_layers(self):
        self.assert_refused(mountinfo=ISO.replace(
            "lowerdir=/nix/.ro-store,", "lowerdir=/nix/.ro-store:/etc,"))
        self.assert_refused(mountinfo=ISO.replace(
            "lowerdir=/nix/.ro-store,", "lowerdir=relative,"))

    def test_reject_fake_overlay_and_missing_root(self):
        self.assert_refused(mountinfo=ISO.replace("overlay overlay", "tmpfs tmpfs"))
        self.assert_refused(mountinfo=ISO.replace(" / / rw,relatime - overlay", " / /root rw,relatime - overlay"))

    def test_optical_boot_device_is_in_protected_set(self):
        optical = {"blockdevices": [
            node("sr0", "11:0", "rom", mount="/iso"),
            node("sdb", "8:16"),
            node("loop0", "7:0", "loop", mount="/nix/.ro-store"),
        ]}
        mounts = ISO.replace("8:1 / /iso", "11:0 / /iso").replace("/dev/sda1 ro", "/dev/sr0 ro")
        result = guard.guard_topology("/dev/sdb", optical, mounts, SWAPS, loop_backings=LOOPS)
        self.assertIn("11:0", result["protected_devices"])

    def test_privileged_preflight_includes_provenance_but_no_write(self):
        review = {"snapshot": {"stable_id": "/dev/disk/by-id/wwn-empty",
                               "device": {"path": "/dev/sdb"}},
                  "sha256": "f" * 64, "write_operations_enabled": False}
        with patch.object(guard.identity, "verify", return_value={"verified": True}), \
             patch.object(media, "sysfs_loop_backings", return_value=LOOPS):
            result = guard.privileged_preflight(review, euid=0,
                lsblk_data=DATA, mountinfo=ISO, swaps=SWAPS)
        self.assertEqual(result["live_media"]["source"], "overlay-squashfs-loop-iso9660")
        self.assertEqual(result["write_operations_enabled"], False)

    def test_mount_parser_rejects_corrupt_records(self):
        with self.assertRaises(media.Refused):
            media.mounts_from_mountinfo("not a kernel mount record")
        with self.assertRaises(media.Refused):
            media.mounts_from_mountinfo("")

    def test_iso_mounted_from_untraceable_loop_is_rejected(self):
        # A mounted ISO9660 filesystem is insufficient if the ISO image
        # itself lives on an untracked loop device.
        data = {"blockdevices": [
            node("loop1", "7:1", "loop", mount="/iso"),
            node("loop0", "7:0", "loop", mount="/nix/.ro-store"),
            node("sdb", "8:16"),
        ]}
        mounts = ISO.replace("8:1 / /iso", "7:1 / /iso").replace(
            "/dev/sda1 ro", "/dev/loop1 ro"
        )
        self.assert_refused(mountinfo=mounts, data=data)

    def test_sysfs_loop_backing_reader_and_mount_escape(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            device = root / "loop2"
            (device / "loop").mkdir(parents=True)
            (device / "dev").write_text("7:2\\n")
            (device / "loop" / "backing_file").write_text("/iso/nix-store.squashfs\\n")
            self.assertEqual(media.sysfs_loop_backings(root),
                             {"7:2": "/iso/nix-store.squashfs"})
        escaped = ISO.replace("/iso ro,relatime", "/iso\\\\040media ro,relatime")
        parsed = media.mounts_from_mountinfo(escaped)
        self.assertIn("/iso media", [m.point for m in parsed])

    def test_ordinary_overlay_with_other_backing_is_not_assumed_safe(self):
        no_iso = ISO.replace("iso9660 /dev/sda1", "ext4 /dev/sda1")
        self.assert_refused(mountinfo=no_iso)


if __name__ == "__main__":
    unittest.main()
