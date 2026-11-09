"""Guarded backend fixtures. No real disks, passwords, or mounts are touched."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import os
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import forge_backend as backend


DEVNO = "8:16"
ID = "/dev/disk/by-id/wwn-fixture"
MAPPER = "/dev/mapper/edos-crypt"
DISK = {
    "path": "/dev/vdb", "name": "vdb", "type": "disk",
    "maj:min": DEVNO, "size": 64 * 1024**3, "model": "Virtual target",
    "serial": "serial-fixture", "wwn": "wwn-fixture",
    "tran": "virtio", "ro": False, "rm": False,
    "children": [
        {"path": "/dev/vdb1", "name": "vdb1", "type": "part", "maj:min": "8:17"},
        {"path": "/dev/vdb2", "name": "vdb2", "type": "part", "maj:min": "8:18",
         "children": [
             {"path": MAPPER, "name": "edos-crypt", "type": "crypt",
              "maj:min": "253:0"}
         ]},
    ],
}
DATA = {"blockdevices": [DISK]}
REVIEW = {
    "snapshot": {
        "stable_id": ID,
        "boot_id": "0c29d241-e413-4374-8b6f-d0de1c9eae5d",
        "device": {k: DISK[k] for k in
                   ("path", "size", "model", "serial", "wwn",
                    "tran", "maj:min", "ro", "rm")},
    },
    "sha256": "f" * 64,
    "write_operations_enabled": False,
}


def entry(point, devno, root, fstype, source):
    return (f"21 1 {devno} {root} {point} rw,relatime - "
            f"{fstype} {source} rw\n")


MOUNTS = "".join([
    entry("/", "0:1", "/", "tmpfs", "tmpfs"),
    entry("/mnt", "0:52", "/@root", "btrfs", MAPPER),
    entry("/mnt/home", "0:53", "/@home", "btrfs", MAPPER),
    entry("/mnt/nix", "0:54", "/@nix", "btrfs", MAPPER),
    entry("/mnt/persist", "0:55", "/@persist", "btrfs", MAPPER),
    entry("/mnt/.snapshots", "0:56", "/@snapshots", "btrfs", MAPPER),
    entry("/mnt/boot", "8:17", "/", "vfat", "/dev/vdb1"),
])


class MountedTargetTests(unittest.TestCase):
    def test_encrypted_subvolumes_and_efi_are_attested(self):
        result = backend.attest_target_mounts(DEVNO, DATA, MOUNTS)
        self.assertEqual(result["status"], "encrypted-target-attested")
        self.assertEqual(result["encrypted_mapper_devno"], "253:0")
        self.assertEqual(len(result["verified_mountpoints"]), 6)
        self.assertFalse(result["write_operations_enabled"])

    def test_missing_extra_or_duplicate_mounts_fail(self):
        cases = [
            MOUNTS.replace(entry("/mnt/persist", "0:55", "/@persist", "btrfs", MAPPER), ""),
            MOUNTS + entry("/mnt/other", "0:57", "/", "ext4", "/dev/vdc"),
            MOUNTS + entry("/mnt/persist", "0:55", "/@persist", "btrfs", MAPPER),
        ]
        for text in cases:
            with self.subTest(text=text[-65:]), self.assertRaises(backend.Refused):
                backend.attest_target_mounts(DEVNO, DATA, text)

    def test_wrong_subvolume_or_unencrypted_root_fails(self):
        for wrong in (
            MOUNTS.replace("/@persist", "/@home"),
            MOUNTS.replace(entry("/mnt", "0:52", "/@root", "btrfs", MAPPER),
                           entry("/mnt", "0:52", "/@root", "btrfs", "/dev/vdb2")),
            MOUNTS.replace(entry("/mnt", "0:52", "/@root", "btrfs", MAPPER),
                           entry("/mnt", "0:52", "/@root", "ext4", MAPPER)),
        ):
            with self.subTest(case=wrong[-70:]), self.assertRaises(backend.Refused):
                backend.attest_target_mounts(DEVNO, DATA, wrong)

    def test_efi_from_second_disk_is_rejected(self):
        data = copy.deepcopy(DATA)
        data["blockdevices"].append({
            "name": "vdc", "path": "/dev/vdc", "maj:min": "8:32",
            "type": "disk", "children": [
                {"name": "vdc1", "path": "/dev/vdc1", "maj:min": "8:33",
                 "type": "part"}],
        })
        mounts = MOUNTS.replace(
            entry("/mnt/boot", "8:17", "/", "vfat", "/dev/vdb1"),
            entry("/mnt/boot", "8:33", "/", "vfat", "/dev/vdc1"),
        )
        with self.assertRaisesRegex(backend.Refused, "EFI"):
            backend.attest_target_mounts(DEVNO, data, mounts)

    def test_crypt_mapper_on_a_different_disk_is_rejected(self):
        data = copy.deepcopy(DATA)
        crypt = data["blockdevices"][0]["children"][1]["children"].pop()
        data["blockdevices"].append({
            "name": "vdc", "path": "/dev/vdc", "maj:min": "8:32",
            "type": "disk", "children": [
                {"name": "vdc2", "path": "/dev/vdc2", "maj:min": "8:34",
                 "type": "part", "children": [crypt]}],
        })
        with self.assertRaisesRegex(backend.Refused, "edos-crypt"):
            backend.attest_target_mounts(DEVNO, data, MOUNTS)

    def test_missing_mapper_and_wrong_device_identifier_are_rejected(self):
        data = copy.deepcopy(DATA)
        data["blockdevices"][0]["children"][1]["children"] = []
        for key, source in ((DEVNO, data), ("8:32", DATA), ("0:99", DATA)):
            with self.subTest(key=key), self.assertRaises(backend.Refused):
                backend.attest_target_mounts(key, source, MOUNTS)

    def test_btrfs_mount_parser_exposes_kernel_root(self):
        from forge_live_media import mounts_from_mountinfo
        found = mounts_from_mountinfo(MOUNTS)
        persist = next(item for item in found if item.point == "/mnt/persist")
        self.assertEqual(persist.root, "/@persist")


class SessionTests(unittest.TestCase):
    def test_no_root_and_wrong_confirmation_never_reach_preflight(self):
        with patch.object(backend.os, "geteuid", return_value=1000), \
             patch.object(backend.guard, "privileged_preflight") as check:
            with self.assertRaises(backend.Refused):
                with backend.prepare_target(REVIEW, "wrong",
                                            username="testpilot", hostname="edos"):
                    pass
            check.assert_not_called()
        with patch.object(backend.os, "geteuid", return_value=0), \
             patch.object(backend.guard, "privileged_preflight") as check:
            with self.assertRaises(backend.Refused):
                with backend.prepare_target(REVIEW, "wrong",
                                            username="testpilot", hostname="edos"):
                    pass
            check.assert_not_called()

    def test_preparation_holds_only_read_only_block_handle_and_closes(self):
        verdict = {"status": "preflight-passed", "disk_id": ID,
                   "target_devno": DEVNO, "write_operations_enabled": False}
        with patch.object(backend.os, "geteuid", return_value=0), \
             patch.object(backend.guard, "privileged_preflight", return_value=verdict), \
             patch.object(backend.os.path, "realpath", return_value="/dev/vdb"), \
             patch.object(backend.os, "open", return_value=33) as openfd, \
             patch.object(backend.os, "close") as closefd, \
             patch.object(backend, "_assert_disk_handle") as block_check, \
             patch.object(backend, "_same_stable_disk") as symlink_check:
            with backend.prepare_target(
                    REVIEW, f"ERASE {ID}", username="testpilot", hostname="edos"
            ) as prepared:
                self.assertEqual(prepared.devno, DEVNO)
                self.assertEqual(prepared.fd, 33)
                self.assertFalse(prepared.used)
            openfd.assert_called_once_with("/dev/vdb", backend.BLOCK_OPEN_FLAGS)
            self.assertFalse(backend.BLOCK_OPEN_FLAGS & os.O_WRONLY)
            closefd.assert_called_once_with(33)
            block_check.assert_called_once_with(33, DEVNO)
            symlink_check.assert_called_once_with(ID, 33)

    def test_preparation_rejects_forged_preflight(self):
        with patch.object(backend.os, "geteuid", return_value=0), \
             patch.object(backend.guard, "privileged_preflight",
                          return_value={"status": "preflight-passed",
                                        "disk_id": ID, "target_devno": DEVNO,
                                        "write_operations_enabled": True}), \
             patch.object(backend.os, "open") as openfd:
            with self.assertRaises(backend.Refused):
                with backend.prepare_target(
                        REVIEW, f"ERASE {ID}", username="testpilot", hostname="edos"):
                    pass
            openfd.assert_not_called()

    def fake_session(self):
        return backend.HeldTarget(
            fd=33, review=copy.deepcopy(REVIEW), username="testpilot",
            hostname="edos", devno=DEVNO,
            deadline=backend.time.monotonic() + 60,
        )

    def test_no_hash_written_when_mounts_untrusted_and_session_consumed(self):
        session = self.fake_session()
        with patch.object(backend, "_root_required"), \
             patch.object(session, "_fresh_device"), \
             patch.object(backend.credentials, "write_user_hash") as writer:
            with self.assertRaises(backend.Refused):
                session.stage_account_hash("strong password 1234", data=DATA,
                                           mountinfo=MOUNTS.replace("/@persist", "/@root"))
            writer.assert_not_called()
            self.assertTrue(session.used)
            with self.assertRaisesRegex(backend.Refused, "consumed"):
                session.stage_account_hash("strong password 1234", data=DATA,
                                           mountinfo=MOUNTS)

    def test_stage_runs_hashing_only_after_root_and_persist_identity(self):
        session = self.fake_session()
        def fake_stat(path, **kwargs):
            if path == "persist":
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755,
                                       st_dev=os.makedev(0, 55))
            raise AssertionError("Unexpected stat path")
        with patch.object(backend, "_root_required"), \
             patch.object(session, "_fresh_device"), \
             patch.object(backend.os, "open", return_value=51), \
             patch.object(backend.os, "close"), \
             patch.object(backend.os, "fstat",
                          return_value=SimpleNamespace(
                              st_mode=stat.S_IFDIR | 0o755,
                              st_uid=0, st_dev=os.makedev(0, 52))), \
             patch.object(backend.os, "stat", side_effect=fake_stat), \
             patch.object(backend, "_assert_disk_handle"), \
             patch.object(backend, "_same_stable_disk"), \
             patch.object(backend.credentials, "hash_user_password",
                          return_value="$6$fixture$hash") as hasher, \
             patch.object(backend.credentials, "write_user_hash",
                          return_value="/persist/eduardos/credentials/testpilot.hash") as writer:
            result = session.stage_account_hash(
                "strong password 1234", data=DATA, mountinfo=MOUNTS,
            )
            hasher.assert_called_once()
            writer.assert_called_once_with(
                51, "testpilot", "$6$fixture$hash", expected_uid=0,
            )
            self.assertEqual(result["status"], "credential-staged")
            self.assertFalse(result["write_operations_enabled"])

    def test_wrong_root_device_prevents_hashing(self):
        session = self.fake_session()
        with patch.object(backend, "_root_required"), \
             patch.object(session, "_fresh_device"), \
             patch.object(backend.os, "open", return_value=51), \
             patch.object(backend.os, "close"), \
             patch.object(backend.os, "fstat",
                          return_value=SimpleNamespace(
                              st_mode=stat.S_IFDIR | 0o755,
                              st_uid=0, st_dev=os.makedev(0, 77))), \
             patch.object(backend.credentials, "hash_user_password") as hasher:
            with self.assertRaisesRegex(backend.Refused, "root mount changed"):
                session.stage_account_hash("strong password 1234",
                                           data=DATA, mountinfo=MOUNTS)
            hasher.assert_not_called()

    def test_prepared_session_invalid_after_timeout(self):
        session = self.fake_session()
        session.deadline = backend.time.monotonic() - 1
        with patch.object(backend, "_root_required"), \
             patch.object(backend.credentials, "hash_user_password") as hasher:
            with self.assertRaisesRegex(backend.Refused, "expired"):
                session.stage_account_hash("strong password 1234",
                                           data=DATA, mountinfo=MOUNTS)
            hasher.assert_not_called()

    def test_postformat_hardware_revalidation_allows_partition_change_only(self):
        # The whole disk acquires partitions after Disko; serial/WWN,
        # capacity, kernel device number, and boot ID must remain unchanged.
        session = self.fake_session()
        with patch.object(backend, "_root_required"), \
             patch.object(backend, "_assert_disk_handle"), \
             patch.object(backend, "_same_stable_disk"), \
             patch.object(backend.identity, "boot_id",
                          return_value=REVIEW["snapshot"]["boot_id"]):
            session._fresh_device(DATA)
            for field, changed in [
                ("serial", "someone-else"), ("wwn", "different"),
                ("size", 999), ("maj:min", "8:32"), ("model", "other-model"),
            ]:
                tampered = copy.deepcopy(DATA)
                tampered["blockdevices"][0][field] = changed
                with self.subTest(field=field), self.assertRaisesRegex(
                    backend.Refused, "identity changed"
                ):
                    session._fresh_device(tampered)

    def test_reject_reboot_or_changed_stable_disk_alias(self):
        session = self.fake_session()
        with patch.object(backend, "_root_required"), \
             patch.object(backend, "_assert_disk_handle"), \
             patch.object(backend, "_same_stable_disk"), \
             patch.object(backend.identity, "boot_id", return_value="new-boot"):
            with self.assertRaisesRegex(backend.Refused, "Boot session"):
                session._fresh_device(DATA)
        with patch.object(backend, "_root_required"), \
             patch.object(backend, "_assert_disk_handle"), \
             patch.object(backend, "_same_stable_disk",
                          side_effect=backend.Refused("alias changed")), \
             patch.object(backend.identity, "boot_id",
                          return_value=REVIEW["snapshot"]["boot_id"]):
            with self.assertRaisesRegex(backend.Refused, "alias changed"):
                session._fresh_device(DATA)

    def test_backend_has_no_destructive_api(self):
        for name in ("install", "format_disk", "run_disko", "partition", "wipe"):
            self.assertFalse(hasattr(backend, name))


if __name__ == "__main__":
    unittest.main()
