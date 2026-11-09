"""PR #33: one-shot privileged preflight protocol, all in-memory fixtures.

No root rights, real devices, formatting, secret collection, or disk writes.
"""
from __future__ import annotations

import copy
from contextlib import nullcontext
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import forge_disk_identity as identity
import forge_privileged_protocol as protocol


ID = "/dev/disk/by-id/wwn-fixture-0001"
DEVICE = {field: None for field in identity.FIELDS}
DEVICE.update({"path": "/dev/vdb", "size": 64 * 1024**3, "maj:min": "8:16"})
REVIEW = {
    "snapshot": {
        "schema": identity.SCHEMA,
        "boot_id": "00000000-0000-0000-0000-000000000001",
        "stable_id": ID,
        "device": DEVICE,
        "layout": [],
        "eligible": True,
        "blockers": [],
    },
    "sha256": "a" * 64,
    "write_operations_enabled": False,
}
REQUEST = {
    "version": protocol.SCHEMA,
    "operation": protocol.OPERATION,
    "review": REVIEW,
    "confirmation": "ERASE " + ID,
    "username": "testpilot",
    "hostname": "edos-installed",
}


def wire(value: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(value, separators=(",", ":")).encode("utf-8"))


class ProtocolTests(unittest.TestCase):
    def test_exact_one_shot_contract(self):
        request = protocol.parse_request(wire(REQUEST))
        self.assertEqual(request.username, "testpilot")
        self.assertEqual(request.hostname, "edos-installed")
        self.assertEqual(request.review, REVIEW)
        self.assertEqual(request.confirmation, "ERASE " + ID)

    def test_reject_any_unknown_top_level_privilege_fields(self):
        for name, value in (
            ("execute", True), ("format", True), ("password", "stolen"),
            ("command", "sh"), ("target", "/dev/sda"),
            ("write_operations_enabled", True), ("allow_writes", True),
            ("luks_passphrase", "secret"), ("nonce", "abc"),
            ("token", "abc"), ("mount", "/mnt"), ("credential_hash", "$6$"),
        ):
            with self.subTest(field=name):
                bad = copy.deepcopy(REQUEST)
                bad[name] = value
                with self.assertRaisesRegex(protocol.Refused, "schema"):
                    protocol.parse_request(wire(bad))

    def test_unknown_nested_fields_and_ineligible_reviews_fail_closed(self):
        for where, name, value in (
            ("review", "execute", True),
            ("snapshot", "password", "fixture-secret"),
            ("device", "execute", True),
            ("snapshot", "eligible", False),
            ("snapshot", "blockers", ["mounted filesystem"]),
            ("review", "write_operations_enabled", True),
            ("snapshot", "schema", "unknown.review"),
            ("review", "sha256", "INVALID"),
        ):
            with self.subTest(where=where, name=name):
                bad = copy.deepcopy(REQUEST)
                location = {
                    "review": bad["review"],
                    "snapshot": bad["review"]["snapshot"],
                    "device": bad["review"]["snapshot"]["device"],
                }[where]
                location[name] = value
                with self.assertRaises(protocol.Refused):
                    protocol.parse_request(wire(bad))

    def test_invalid_identity_and_confirmation_are_refused(self):
        cases = [
            ("version", "eduardos.forge.privileged.v2"),
            ("operation", "install"),
            ("operation", "stage-account"),
            ("confirmation", "ERASE /dev/sda"),
            ("confirmation", "ERASE " + ID + " "),
            ("confirmation", True),
            ("username", "root"),
            ("username", "forge"),
            ("username", "../root"),
            ("username", True),
            ("hostname", "desktop.local"),
            ("hostname", "host-"),
            ("hostname", True),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                bad = copy.deepcopy(REQUEST)
                bad[name] = value
                with self.assertRaises(protocol.Refused):
                    protocol.parse_request(wire(bad))
        for invalid in ("/dev/sda", "/dev/vda", "/dev/disk/by-id/../../sda",
                        "/dev/disk/by-id/evil/alias", "/tmp/usb"):
            with self.subTest(disk=invalid):
                bad = copy.deepcopy(REQUEST)
                bad["review"]["snapshot"]["stable_id"] = invalid
                bad["confirmation"] = "ERASE " + invalid
                with self.assertRaises(protocol.Refused):
                    protocol.parse_request(wire(bad))

    def test_json_framing_rejects_empty_binary_overlength_duplicates(self):
        samples = [
            b"", b"not-json", b"{}", b"[]", b"null",
            b"{}{}", b"\xff",
            b" " * (protocol.MAX_REQUEST_BYTES + 1),
            json.dumps(REQUEST).encode() + b"\n" + json.dumps(REQUEST).encode(),
            json.dumps(REQUEST).replace(
                '"version":', '"version": "duplicate", "version":', 1
            ).encode(),
            json.dumps(REQUEST).replace(
                '"hostname": "edos-installed"', '"hostname": NaN'
            ).encode(),
        ]
        for n, payload in enumerate(samples):
            with self.subTest(case=n):
                with self.assertRaises(protocol.Refused):
                    protocol.parse_request(io.BytesIO(payload))
        with self.assertRaises(protocol.Refused):
            protocol.parse_request(io.StringIO(json.dumps(REQUEST)))

    def test_nonroot_cannot_read_input_or_call_backend(self):
        class NoRead:
            def read(self, *_):
                raise AssertionError("Input must not be inspected as non-root")
        with patch.object(protocol.os, "geteuid", return_value=1000), \
             patch.object(protocol.backend, "prepare_target") as backend:
            with self.assertRaisesRegex(protocol.Refused, "Root-only"):
                protocol.handle_request(NoRead())
            backend.assert_not_called()

    def test_root_dispatch_uses_existing_guarded_read_only_backend(self):
        held = SimpleNamespace(
            review=REVIEW, devno="8:16", username="testpilot",
            hostname="edos-installed", fd=33,
        )
        with patch.object(protocol.os, "geteuid", return_value=0), \
             patch.object(protocol.backend, "prepare_target",
                          return_value=nullcontext(held)) as prepare:
            report = protocol.handle_request(wire(REQUEST))
        prepare.assert_called_once_with(
            REVIEW, "ERASE " + ID, username="testpilot",
            hostname="edos-installed",
        )
        self.assertEqual(report["status"], "attested-read-only")
        self.assertEqual(report["target_devno"], "8:16")
        self.assertEqual(report["disk_review_sha256"], REVIEW["sha256"])
        for key in ("write_operations_enabled", "destructive_disk_operations_enabled",
                    "credential_writes_enabled", "authorization_to_write"):
            self.assertIs(report[key], False)
        self.assertNotIn("fd", report)
        self.assertNotIn("capability", report)
        self.assertNotIn("nonce", report)
        self.assertNotIn("password", report)

    def test_rejects_privileged_guard_failure_without_leaking_request(self):
        output = io.StringIO()
        with patch.object(protocol.os, "geteuid", return_value=0), \
             patch.object(protocol.backend, "prepare_target",
                          side_effect=protocol.backend.Refused("device changed")):
            code = protocol.main(
                [], input_stream=wire(REQUEST), output_stream=output
            )
        self.assertEqual(code, 2)
        body = json.loads(output.getvalue())
        self.assertEqual(body["status"], "refused")
        self.assertFalse(body["authorization_to_write"])
        self.assertFalse(body["write_operations_enabled"])
        self.assertNotIn("testpilot", output.getvalue())
        self.assertNotIn(ID, output.getvalue())
        self.assertNotIn("device changed", output.getvalue())

    def test_main_has_exactly_one_json_line_and_no_writable_reply(self):
        held = SimpleNamespace(
            review=REVIEW, devno="8:16", username="testpilot",
            hostname="edos-installed", fd=33,
        )
        output = io.StringIO()
        with patch.object(protocol.os, "geteuid", return_value=0), \
             patch.object(protocol.backend, "prepare_target",
                          return_value=nullcontext(held)):
            self.assertEqual(protocol.main(
                [], input_stream=wire(REQUEST), output_stream=output
            ), 0)
        self.assertTrue(output.getvalue().endswith("\n"))
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertIs(json.loads(output.getvalue())["authorization_to_write"], False)


if __name__ == "__main__":
    unittest.main()
