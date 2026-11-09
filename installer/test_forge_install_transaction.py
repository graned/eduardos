"""In-memory failure injection for the QEMU-only install transaction.

No root privileges, subprocess calls, mounted devices or disk writes.
"""
from __future__ import annotations

import unittest

from forge_install_transaction import InstallationTransaction, Refused


class InstallTransactionTests(unittest.TestCase):
    def fixture(self, fail_at=None):
        calls = []
        events = []

        def step(name):
            def run():
                calls.append(name)
                if fail_at == name:
                    raise RuntimeError("injected failure")
            return run

        tx = InstallationTransaction(
            preflight=step("guard"),
            format_disk=step("format"),
            audit_mounted_target=step("audit"),
            stage_credential_hash=step("credentials"),
            install_system=step("install"),
            emit=events.append,
        )
        return tx, calls, events

    def test_successful_order_enforces_two_audits(self):
        tx, calls, events = self.fixture()
        self.assertIsNone(tx.run())
        self.assertEqual(calls, [
            "guard", "format", "audit", "credentials", "audit", "install",
        ])
        self.assertEqual(events, [
            "guarded", "format-started", "formatted",
            "mounted-attested", "credential-staged", "re-attested",
            "install-started", "installed",
        ])
        self.assertTrue(tx.format_started)
        self.assertEqual(tx.phase, "installed")

    def test_reuse_is_refused_even_after_success(self):
        tx, calls, events = self.fixture()
        tx.run()
        with self.assertRaisesRegex(Refused, "consumed"):
            tx.run()
        self.assertEqual(calls.count("format"), 1)
        self.assertEqual(events.count("installed"), 1)

    def test_preflight_failure_never_starts_format(self):
        tx, calls, events = self.fixture("guard")
        with self.assertRaisesRegex(RuntimeError, "injected failure"):
            tx.run()
        self.assertEqual(calls, ["guard"])
        self.assertFalse(tx.format_started)
        self.assertEqual(tx.phase, "halted-before-format")
        self.assertEqual(events, ["halted-before-format"])
        with self.assertRaises(Refused):
            tx.run()
        self.assertEqual(calls, ["guard"])

    def test_format_failure_marks_irreversible_boundary_first(self):
        tx, calls, events = self.fixture("format")
        with self.assertRaises(RuntimeError):
            tx.run()
        self.assertEqual(calls, ["guard", "format"])
        self.assertTrue(tx.format_started)
        self.assertEqual(events, [
            "guarded", "format-started", "halted-after-format-started",
        ])
        with self.assertRaises(Refused):
            tx.run()

    def test_bad_mount_audit_blocks_all_following_steps(self):
        tx, calls, events = self.fixture("audit")
        with self.assertRaises(RuntimeError):
            tx.run()
        self.assertEqual(calls, ["guard", "format", "audit"])
        self.assertNotIn("credentials", calls)
        self.assertNotIn("install", calls)
        self.assertEqual(tx.phase, "halted-after-format-started")

    def test_credential_failure_blocks_install(self):
        tx, calls, events = self.fixture("credentials")
        with self.assertRaises(RuntimeError):
            tx.run()
        self.assertEqual(calls, [
            "guard", "format", "audit", "credentials",
        ])
        self.assertNotIn("install", calls)
        self.assertEqual(tx.phase, "halted-after-format-started")

    def test_second_audit_failure_blocks_install(self):
        calls = []
        events = []
        seen_audits = 0

        def audit():
            nonlocal seen_audits
            seen_audits += 1
            calls.append("audit")
            if seen_audits == 2:
                raise RuntimeError("changed mounted target")

        tx = InstallationTransaction(
            preflight=lambda: calls.append("guard"),
            format_disk=lambda: calls.append("format"),
            audit_mounted_target=audit,
            stage_credential_hash=lambda: calls.append("credentials"),
            install_system=lambda: calls.append("install"),
            emit=events.append,
        )
        with self.assertRaisesRegex(RuntimeError, "changed mounted target"):
            tx.run()
        self.assertEqual(calls, [
            "guard", "format", "audit", "credentials", "audit",
        ])
        self.assertEqual(events[-1], "halted-after-format-started")
        self.assertNotIn("install", calls)

    def test_install_failure_cannot_be_retried_or_rolled_back(self):
        tx, calls, events = self.fixture("install")
        with self.assertRaises(RuntimeError):
            tx.run()
        self.assertEqual(calls[-1], "install")
        self.assertTrue(tx.format_started)
        self.assertEqual(tx.phase, "halted-after-format-started")
        with self.assertRaisesRegex(Refused, "consumed"):
            tx.run()
        self.assertEqual(calls.count("install"), 1)

    def test_constructor_rejects_missing_step_and_bad_reporter(self):
        callbacks = {
            "preflight": lambda: None,
            "format_disk": lambda: None,
            "audit_mounted_target": lambda: None,
            "stage_credential_hash": lambda: None,
            "install_system": lambda: None,
        }
        for name in callbacks:
            with self.subTest(step=name):
                with self.assertRaisesRegex(Refused, "not callable"):
                    InstallationTransaction(**{**callbacks, name: None})
        with self.assertRaisesRegex(Refused, "reporter"):
            InstallationTransaction(**callbacks, emit="a command")

    def test_progress_is_fixed_vocabulary_no_secret_data(self):
        tx, calls, events = self.fixture()
        tx.run()
        self.assertTrue(all(
            event in {
                "guarded", "format-started", "formatted",
                "mounted-attested", "credential-staged", "re-attested",
                "install-started", "installed",
            } for event in events
        ))
        self.assertEqual(len(events), 8)


if __name__ == "__main__":
    unittest.main()
