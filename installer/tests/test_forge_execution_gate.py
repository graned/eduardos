"""Mocked gate integration tests: no real disk, root, or subprocesses."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_backend as backend
import forge_execution_gate as gate
import forge_physical_command_policy as policy

GOOD = {
    "disko_script": "/nix/store/" + "a" * 32 + "-disko/bin/disko",
    "system_closure": "/nix/store/" + "b" * 32 + "-system",
}


def held_target():
    return backend.HeldTarget(
        fd=42,
        review={"snapshot": {"stable_id": "/dev/disk/by-id/wwn-0xdeadbeef",
                             "device": {"path": "/dev/vdb"}}},
        username="testpilot", hostname="edos",
        devno="253:16", deadline=99999999999.0,
    )


class TrustedReadOnlyGateTests(unittest.TestCase):
    def test_rechecks_and_reviews_fixed_plan_without_executing(self):
        held = held_target()
        safe = {
            "status": "preformat-attested-read-only",
            "target_devno": held.devno,
            "write_operations_enabled": False,
            "authorization_to_write": False,
            "destructive_disk_operations_enabled": False,
        }
        with mock.patch.object(gate.os, "geteuid", return_value=0), \
             mock.patch.object(held, "reattest_preformat", return_value=safe) as first, \
             mock.patch.object(held, "_fresh_device") as final, \
             mock.patch.object(backend.identity, "probe", return_value={}):
            report = gate.review_before_execution(held, **GOOD)
        first.assert_called_once()
        final.assert_called_once()
        self.assertEqual(report["phases"], list(policy.PHASES))
        self.assertFalse(report["authorization_to_write"])
        self.assertFalse(report["executable"])
        self.assertFalse(report["destructive_disk_operations_enabled"])

    def test_root_and_session_required(self):
        held = held_target()
        with mock.patch.object(gate.os, "geteuid", return_value=1000):
            with self.assertRaises(gate.Refused):
                gate.review_before_execution(held, **GOOD)
        held.used = True
        with mock.patch.object(gate.os, "geteuid", return_value=0):
            with self.assertRaises(gate.Refused):
                gate.review_before_execution(held, **GOOD)

    def test_rejects_dishonest_reattest_status_and_flags(self):
        held = held_target()
        base = {
            "status": "preformat-attested-read-only",
            "target_devno": held.devno,
            "write_operations_enabled": False,
            "authorization_to_write": False,
            "destructive_disk_operations_enabled": False,
        }
        cases = (
            {"status": "ready-to-erase"},
            {"target_devno": "8:0"},
            {"write_operations_enabled": True},
            {"authorization_to_write": True},
            {"destructive_disk_operations_enabled": True},
        )
        for wrong in cases:
            with self.subTest(wrong=wrong), \
                 mock.patch.object(gate.os, "geteuid", return_value=0), \
                 mock.patch.object(held, "reattest_preformat",
                                   return_value={**base, **wrong}), \
                 mock.patch.object(held, "_fresh_device") as final:
                with self.assertRaises(gate.Refused):
                    gate.review_before_execution(held, **GOOD)
                final.assert_not_called()

    def test_fails_closed_if_device_changes_during_plan_review(self):
        held = held_target()
        base = {
            "status": "preformat-attested-read-only",
            "target_devno": held.devno,
            "write_operations_enabled": False,
            "authorization_to_write": False,
            "destructive_disk_operations_enabled": False,
        }
        with mock.patch.object(gate.os, "geteuid", return_value=0), \
             mock.patch.object(held, "reattest_preformat", return_value=base), \
             mock.patch.object(backend.identity, "probe", return_value={}), \
             mock.patch.object(held, "_fresh_device",
                               side_effect=backend.Refused("device changed")):
            with self.assertRaises(backend.Refused):
                gate.review_before_execution(held, **GOOD)

    def test_arbitrary_commands_still_refused(self):
        held = held_target()
        base = {
            "status": "preformat-attested-read-only",
            "target_devno": held.devno,
            "write_operations_enabled": False,
            "authorization_to_write": False,
            "destructive_disk_operations_enabled": False,
        }
        with mock.patch.object(gate.os, "geteuid", return_value=0), \
             mock.patch.object(held, "reattest_preformat", return_value=base):
            with self.assertRaises(policy.Refused):
                gate.review_before_execution(held, disko_script="/bin/sh",
                                             system_closure=GOOD["system_closure"])


if __name__ == "__main__":
    unittest.main()
