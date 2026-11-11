"""Mock-only trusted recovery audit integration: never reads a real disk."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_root_recovery_audit as audit

STORE = Path("/var/lib/eduardos-attempts")
DISK = "/dev/disk/by-id/wwn-0x123"
EVIDENCE = {
    "status": "separate-physical-backing-candidate",
    "store_disk_devno": "8:16",
    "install_target_devno": "8:0",
    "durability_proven": False,
    "authorization_to_write": False,
    "write_operations_enabled": False,
}
RECOVERY = {
    "status": "manual-recovery-required",
    "durability_proven": False,
    "write_operations_enabled": False,
    "authorization_to_write": False,
    "automatic_retry_enabled": False,
}


class RootRecoveryAuditTests(unittest.TestCase):
    def checks(self, *, roots=(EVIDENCE, EVIDENCE), reports=RECOVERY,
               mounts=("mountinfo", "mountinfo")):
        with mock.patch.object(audit.os, "geteuid", return_value=0), \
             mock.patch.object(audit.Path, "read_text", side_effect=list(mounts)), \
             mock.patch.object(audit.identity, "probe",
                               side_effect=[{"sample": 1}, {"sample": 2}]) as probe, \
             mock.patch.object(audit.ancestry, "attest_separate_backing",
                               side_effect=list(roots)) as ancestry, \
             mock.patch.object(audit.recovery, "report",
                               return_value=reports) as recovery:
            result = audit.audit(store=STORE, stable_id=DISK, target_devno="8:0")
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(ancestry.call_count, 2)
        recovery.assert_called_once_with(STORE, DISK, mountinfo="mountinfo")
        return result

    def test_real_probe_sequence_is_fail_closed_and_read_only(self):
        result = self.checks()
        self.assertEqual(result["status"], "manual-recovery-required")
        self.assertFalse(result["authorization_to_write"])
        self.assertFalse(result["automatic_retry_enabled"])
        self.assertFalse(result["durability_proven"])

    def test_missing_attempt_is_not_retry_authority(self):
        result = self.checks(reports={**RECOVERY, "status": "unproven-no-record"})
        self.assertEqual(result["status"], "unproven-no-record")
        self.assertFalse(result["automatic_retry_enabled"])

    def test_replaced_mount_and_disk_ancestry_are_refused(self):
        with self.assertRaises(audit.Refused):
            self.checks(roots=(EVIDENCE, {**EVIDENCE, "store_disk_devno": "8:32"}))
        with self.assertRaises(audit.Refused):
            self.checks(mounts=("mountinfo", "changed mountinfo"))

    def test_root_required_and_unsafe_evidence_refused(self):
        with mock.patch.object(audit.os, "geteuid", return_value=1000):
            with self.assertRaises(audit.Refused):
                audit.audit(store=STORE, stable_id=DISK, target_devno="8:0")
        with self.assertRaises(audit.Refused):
            self.checks(roots=({**EVIDENCE, "durability_proven": True}, EVIDENCE))
        with self.assertRaises(audit.Refused):
            self.checks(reports={**RECOVERY, "automatic_retry_enabled": True})

    def test_missing_or_ambiguous_recovery_fails_closed(self):
        with mock.patch.object(audit.os, "geteuid", return_value=0), \
             mock.patch.object(audit.Path, "read_text", return_value="mountinfo"), \
             mock.patch.object(audit.identity, "probe", return_value={}), \
             mock.patch.object(audit.ancestry, "attest_separate_backing",
                               side_effect=audit.ancestry.Refused("ambiguous")):
            with self.assertRaises(audit.Refused):
                audit.audit(store=STORE, stable_id=DISK, target_devno="8:0")


if __name__ == "__main__":
    unittest.main()
