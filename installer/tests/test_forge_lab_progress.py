"""Unit checks for exact real phase-event observation (no disk operations)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge_lab_progress import ORDER, PREFIX, Refused, assess


def log(*events):
    return "\n".join(PREFIX + event for event in events) + "\n"


class ProgressContractTests(unittest.TestCase):
    def test_complete_success_is_exactly_all_ordered_phases(self):
        result = assess("initial safety checks\n" + log(*ORDER), process_returncode=0)
        self.assertEqual(result["status"], "installed-lab-only")
        self.assertTrue(result["complete"])
        self.assertFalse(result["automatic_retry_enabled"])
        self.assertFalse(result["authorization_to_write"])

    def test_missing_duplicate_out_of_order_and_unknown_events_refuse(self):
        invalid = (
            log(*ORDER[:-1]),
            log(*ORDER[:3], ORDER[2], *ORDER[3:]),
            log(ORDER[1], ORDER[0]),
            log(*ORDER, "run-anything"),
            log(*ORDER, "installed"),
        )
        for evidence in invalid:
            with self.subTest(evidence=evidence), self.assertRaises(Refused):
                assess(evidence, process_returncode=0)

    def test_partial_format_failure_is_manual_recovery(self):
        result = assess(
            log("guarded", "format-started", "halted-after-format-started"),
            process_returncode=3,
        )
        self.assertEqual(result["status"], "manual-recovery-required")
        self.assertFalse(result["complete"])

    def test_preformat_failure_can_never_be_success(self):
        result = assess(log("halted-before-format"), process_returncode=2)
        self.assertEqual(result["status"], "aborted-before-format")
        self.assertFalse(result["automatic_retry_enabled"])
        with self.assertRaises(Refused):
            assess(log("halted-after-format-started"), process_returncode=2)

    def test_power_loss_or_sigkill_keeps_disk_state_unknown(self):
        result = assess(log("guarded", "format-started"), process_returncode=-9)
        self.assertEqual(result["status"], "incomplete-unknown-disk-state")
        self.assertFalse(result["complete"])
        result = assess("", process_returncode=-9)
        self.assertFalse(result["automatic_retry_enabled"])

    def test_contradictory_terminal_states_refuse(self):
        for evidence, exit_code in (
            (log(*ORDER, "halted-after-format-started"), 0),
            (log("guarded", "halted-before-format", "installed"), 3),
            (log("guarded", "format-started", "halted-before-format"), 3),
            (log("guarded", "format-started", "halted-after-format-started"), 0),
        ):
            with self.subTest(evidence=evidence), self.assertRaises(Refused):
                assess(evidence, process_returncode=exit_code)

    def test_bounded_and_typed_input(self):
        with self.assertRaises(Refused):
            assess("x" * (2 * 1024 * 1024 + 1), process_returncode=0)
        with self.assertRaises(Refused):
            assess(log(*ORDER), process_returncode=True)


if __name__ == "__main__":
    unittest.main()
