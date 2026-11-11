"""Non-destructive tests of persistent-store mount evidence."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge_attempt_store_provenance import (
    Refused, mount_evidence, check_candidate_directory
)

POINT = "/var/lib/eduardos-attempts"
def entry(fstype="ext4", source="/dev/vdb1", point=POINT, mode="rw,relatime",
          root="/", devno="253:1"):
    return f"38 21 {devno} {root} {point} {mode} - {fstype} {source} rw\n"


class StoreEvidenceTests(unittest.TestCase):
    def test_explicit_local_mount_is_only_candidate_not_durability_proof(self):
        result = mount_evidence(POINT, entry())
        self.assertEqual(result["status"], "candidate-local-mount")
        self.assertFalse(result["durability_proven"])
        self.assertFalse(result["write_operations_enabled"])
        self.assertFalse(result["authorization_to_write"])

    def test_volatile_network_and_overlay_mounts_refused(self):
        for fstype, source in (
            ("tmpfs", "tmpfs"),
            ("overlay", "overlay"),
            ("nfs", "server:/share"),
            ("ramfs", "ramfs"),
            ("ext4", "server:/share"),
        ):
            with self.subTest(fstype=fstype, source=source):
                with self.assertRaises(Refused):
                    mount_evidence(POINT, entry(fstype=fstype, source=source))

    def test_missing_duplicate_readonly_and_bind_subtree_refused(self):
        bad = (
            entry(point="/elsewhere"),
            entry() + entry(),
            entry(mode="ro,relatime"),
            entry(root="/subdir"),
            entry(devno="n/a"),
            "not kernel mountinfo",
        )
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(Refused):
                    mount_evidence(POINT, raw)

    def test_current_directory_is_not_sufficient_without_mount_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store"
            path.mkdir(mode=0o700)
            with self.assertRaises(Refused):
                check_candidate_directory(path, entry(point="/other"))
            with self.assertRaises(Refused):
                check_candidate_directory(path, entry(point=tmp))
            path.chmod(0o755)
            with self.assertRaises(Refused):
                check_candidate_directory(path, entry(point=str(path)))

    def test_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            store.mkdir(mode=0o700)
            link = Path(tmp) / "link"
            link.symlink_to(store, target_is_directory=True)
            with self.assertRaises(Refused):
                check_candidate_directory(link, entry(point=str(link)))


if __name__ == "__main__":
    unittest.main()
