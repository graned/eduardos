"""Persistent recovery reporting tests with mocked root and mount evidence."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_persistent_recovery as recovery
from forge_attempt_store_provenance import Refused as MountRefused
from forge_persistent_attempt import Refused as AttemptRefused

STORE = Path("/run/unit-test-only-store")
DISK = "/dev/disk/by-id/wwn-0x123"
EVIDENCE = {
    "status": "candidate-local-mount",
    "durability_proven": False,
    "authorization_to_write": False,
    "write_operations_enabled": False,
}


class RecoveryReportTests(unittest.TestCase):
    def test_prior_attempt_requires_manual_recovery(self):
        with mock.patch.object(recovery.os, "geteuid", return_value=0), \
             mock.patch.object(recovery.provenance, "check_candidate_directory",
                               return_value=EVIDENCE), \
             mock.patch.object(recovery.attempts, "inspect_attempt",
                               return_value="reserved-no-auto-retry"):
            result = recovery.report(STORE, DISK, mountinfo="fixture")
        self.assertEqual(result["status"], "manual-recovery-required")
        self.assertFalse(result["automatic_retry_enabled"])
        self.assertFalse(result["write_operations_enabled"])
        self.assertFalse(result["durability_proven"])

    def test_missing_marker_is_never_permission_to_retry(self):
        with mock.patch.object(recovery.os, "geteuid", return_value=0), \
             mock.patch.object(recovery.provenance, "check_candidate_directory",
                               return_value=EVIDENCE), \
             mock.patch.object(recovery.attempts, "inspect_attempt", return_value="none"):
            result = recovery.report(STORE, DISK, mountinfo="fixture")
        self.assertEqual(result["status"], "unproven-no-record")
        self.assertIn("DOES NOT prove", result["advice"])
        self.assertFalse(result["authorization_to_write"])
        self.assertFalse(result["automatic_retry_enabled"])

    def test_nonroot_and_bad_store_refuse(self):
        with mock.patch.object(recovery.os, "geteuid", return_value=1000):
            with self.assertRaises(recovery.Refused):
                recovery.report(STORE, DISK, mountinfo="fixture")
        with mock.patch.object(recovery.os, "geteuid", return_value=0), \
             mock.patch.object(recovery.provenance, "check_candidate_directory",
                               side_effect=MountRefused("volatile")):
            with self.assertRaises(recovery.Refused):
                recovery.report(STORE, DISK, mountinfo="fixture")

    def test_bad_or_unreadable_marker_refuses(self):
        with mock.patch.object(recovery.os, "geteuid", return_value=0), \
             mock.patch.object(recovery.provenance, "check_candidate_directory",
                               return_value=EVIDENCE), \
             mock.patch.object(recovery.attempts, "inspect_attempt",
                               side_effect=AttemptRefused("partial marker")):
            with self.assertRaises(recovery.Refused):
                recovery.report(STORE, DISK, mountinfo="fixture")

    def test_unknown_state_cannot_be_treated_as_safe(self):
        with mock.patch.object(recovery.os, "geteuid", return_value=0), \
             mock.patch.object(recovery.provenance, "check_candidate_directory",
                               return_value=EVIDENCE), \
             mock.patch.object(recovery.attempts, "inspect_attempt",
                               return_value="installed"):
            with self.assertRaises(recovery.Refused):
                recovery.report(STORE, DISK, mountinfo="fixture")


if __name__ == "__main__":
    unittest.main()
