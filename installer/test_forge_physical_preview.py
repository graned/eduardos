"""Read-only physical execution manifest tests. ALL synthetic, no root or disk.

The real root-held block descriptor and kernel topology guard are covered
by existing Forge PR #33 tests and PR #39 adversarial QEMU tests. This
suite injects hotplug/identity failures and enforces the NO-WRITE output.
"""
from __future__ import annotations

import copy
from contextlib import nullcontext
import io
import json
import re
import unittest
from unittest.mock import patch

import forge_authorization as auth
import forge_backend as backend
import forge_disk_identity as identity
import forge_physical_preview as preview
import forge_privileged_guard as guard
import forge_privileged_protocol as protocol

DISK = "/dev/disk/by-id/wwn-edos-physical-preview-fixture"
DEVICE = {key: None for key in identity.FIELDS}
DEVICE.update({
    "path": "/dev/vdb",
    "size": 64 * 1024**3,
    "maj:min": "8:16",
    "serial": "QEMU-FAKE-DEVICE",
})
SNAP = {
    "schema": identity.SCHEMA,
    "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
    "stable_id": DISK,
    "device": DEVICE,
    "layout": [],
    "eligible": True,
    "blockers": [],
}
REVIEW = {
    "snapshot": SNAP,
    "sha256": identity.fingerprint(SNAP),
    "write_operations_enabled": False,
}
REQUEST = {
    "version": protocol.SCHEMA,
    "operation": protocol.OPERATION,
    "review": REVIEW,
    "confirmation": auth.confirm_text(DISK),
    "username": "testpilot",
    "hostname": "edos-installed",
}
PROOF = {
    "status": "preflight-passed",
    "target_devno": "8:16",
    "disk_id": DISK,
    "disk_review_sha256": REVIEW["sha256"],
    "write_operations_enabled": False,
}


def wire(msg=REQUEST):
    return io.BytesIO(json.dumps(msg, separators=(",", ":")).encode())


def held_target():
    return backend.HeldTarget(
        fd=77, review=copy.deepcopy(REVIEW), username="testpilot",
        hostname="edos-installed", devno="8:16", deadline=9999999999.0,
    )


class PhysicalPreviewTests(unittest.TestCase):
    def evaluate(self, held=None, *, proof=None):
        target = held_target() if held is None else held
        audit = PROOF if proof is None else proof
        with patch.object(preview.os, "geteuid", return_value=0), \
             patch.object(preview.identity, "probe",
                          side_effect=[{"first": 1}, {"second": 2}]) as probe, \
             patch.object(preview.identity, "verify",
                          return_value={"verified": True}) as verify, \
             patch.object(preview.guard, "privileged_preflight",
                          return_value=audit) as preflight, \
             patch.object(target, "_fresh_device") as fresh:
            result = preview.OneShotPhysicalPreview(target).build()
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(fresh.call_count, 2)
        self.assertEqual(preflight.call_count, 1)
        self.assertEqual(preflight.call_args.kwargs["lsblk_data"], {"first": 1})
        return result

    def test_manifest_covers_existing_disko_intent_without_executable_commands(self):
        doc = self.evaluate()
        self.assertEqual(doc["status"], "preview-read-only")
        spec = doc["manifest"]["storage_intent"]
        self.assertEqual(spec["partition_table"], "gpt")
        self.assertEqual(spec["esp_size_mib"], 1024)
        self.assertEqual(spec["encryption"], "luks2")
        self.assertEqual(spec["encrypted_filesystem"], "btrfs")
        self.assertEqual(spec["subvolumes"], [
            "@root", "@home", "@nix", "@persist", "@snapshots",
        ])
        self.assertEqual(
            set(spec["mountpoints"]),
            set(backend.TARGET_ROOT + suffix
                for suffix in backend.TARGET_MOUNTS),
        )
        self.assertEqual(doc["manifest"]["disk_id"], DISK)
        self.assertEqual(doc["manifest"]["target_devno"], "8:16")
        self.assertEqual(len(doc["manifest"]["intended_phases"]), 8)
        for phase in doc["manifest"]["intended_phases"]:
            self.assertEqual(set(phase), {"id", "description", "executable"})
            self.assertIs(phase["executable"], False)
            self.assertNotIn("command", phase)
            self.assertNotIn("argv", phase)
        for object_ in (doc, doc["manifest"]):
            for flag in (
                "write_operations_enabled",
                "destructive_disk_operations_enabled",
                "credential_writes_enabled", "authorization_to_write",
            ):
                self.assertIs(object_[flag], False)
        content = json.dumps(doc)
        self.assertNotIn("password", content.lower())
        self.assertNotIn("passphrase", content.lower())
        self.assertNotIn('"fd":', content)
        self.assertNotIn("mkfs.", content)
        self.assertNotIn("sudo", content)

    def test_manifest_digest_is_deterministic_and_not_an_authorization(self):
        first = self.evaluate()
        second = self.evaluate()
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        self.assertTrue(re.fullmatch(
            r"[a-f0-9]{64}", first["manifest_sha256"],
        ))
        self.assertEqual(
            first["manifest_sha256"],
            preview.hashlib.sha256(
                identity.canonical(first["manifest"]),
            ).hexdigest(),
        )
        changed = copy.deepcopy(first["manifest"])
        changed["hostname"] = "other-host"
        self.assertNotEqual(
            first["manifest_sha256"],
            preview.hashlib.sha256(identity.canonical(changed)).hexdigest(),
        )

    def test_one_shot_is_consumed_before_any_failed_audit(self):
        held = held_target()
        session = preview.OneShotPhysicalPreview(held)
        with patch.object(preview.os, "geteuid", return_value=0), \
             patch.object(preview.identity, "probe",
                          side_effect=identity.Refused("disk hotplugged")):
            with self.assertRaisesRegex(identity.Refused, "hotplugged"):
                session.build()
        with self.assertRaisesRegex(preview.Refused, "consumed"):
            session.build()

    def test_rejects_held_review_and_account_mutations(self):
        for name, change in (
            ("account", lambda h: setattr(h, "username", "hacker")),
            ("host", lambda h: setattr(h, "hostname", "badhost")),
            ("device", lambda h: setattr(h, "devno", "8:32")),
            ("disk", lambda h: h.review["snapshot"].update(
                stable_id="/dev/disk/by-id/wwn-different",
            )),
            ("digest", lambda h: h.review.update(sha256="f" * 64)),
        ):
            with self.subTest(name=name):
                held = held_target()
                session = preview.OneShotPhysicalPreview(held)
                change(held)
                with patch.object(preview.os, "geteuid", return_value=0), \
                     patch.object(preview.identity, "probe") as probe:
                    with self.assertRaisesRegex(preview.Refused, "changed"):
                        session.build()
                    probe.assert_not_called()

    def test_denies_modified_disk_topology_and_live_mounts(self):
        for stage in ("first-identity", "held-fd", "protected-system",
                      "second-identity"):
            with self.subTest(stage=stage):
                held = held_target()
                with patch.object(preview.os, "geteuid", return_value=0), \
                     patch.object(preview.identity, "probe",
                                  side_effect=[{"time": 1}, {"time": 2}]), \
                     patch.object(preview.identity, "verify",
                                  side_effect=(
                                      [identity.Refused("disk changed")]
                                      if stage == "first-identity" else
                                      [None, identity.Refused("hotplugged")]
                                      if stage == "second-identity" else
                                      [None, None]
                                  )), \
                     patch.object(preview.guard, "privileged_preflight",
                                  side_effect=(
                                      guard.Refused("boot device mounted")
                                      if stage == "protected-system" else None
                                  ), return_value=PROOF), \
                     patch.object(held, "_fresh_device",
                                  side_effect=(
                                      backend.Refused("held fd differs")
                                      if stage == "held-fd" else None
                                  )):
                    with self.assertRaises(
                        (identity.Refused, backend.Refused, guard.Refused)
                    ):
                        preview.OneShotPhysicalPreview(held).build()

    def test_refuses_mismatched_guard_results_or_write_flag(self):
        for key, bad in (
            ("target_devno", "8:32"),
            ("disk_id", "/dev/disk/by-id/wwn-else"),
            ("disk_review_sha256", "0" * 64),
            ("write_operations_enabled", True),
            ("status", "failed"),
        ):
            with self.subTest(field=key):
                proof = {**PROOF, key: bad}
                held = held_target()
                with patch.object(preview.os, "geteuid", return_value=0), \
                     patch.object(preview.identity, "probe",
                                  return_value={}), \
                     patch.object(preview.identity, "verify"), \
                     patch.object(preview.guard, "privileged_preflight",
                                  return_value=proof), \
                     patch.object(held, "_fresh_device"):
                    with self.assertRaisesRegex(
                        preview.Refused, "audit refused",
                    ):
                        preview.OneShotPhysicalPreview(held).build()

    def test_nonroot_does_not_even_read_request(self):
        class DoNotRead:
            def read(self, *args):
                raise AssertionError("Should not inspect any input")
        with patch.object(preview.os, "geteuid", return_value=1000), \
             patch.object(preview.backend, "prepare_target") as holder:
            with self.assertRaisesRegex(preview.Refused, "Root-only"):
                preview.preview_request(DoNotRead())
            holder.assert_not_called()

    def test_exact_readonly_protocol_refuses_format_and_password_fields(self):
        for key, val in (
            ("operation", "execute-install"),
            ("operation", "format-disk"),
            ("format", True),
            ("execute", True),
            ("password", "secret"),
            ("luks_key", "secret"),
            ("script", "/tmp/a.sh"),
        ):
            with self.subTest(field=key, value=val):
                bad = copy.deepcopy(REQUEST)
                bad[key] = val
                with patch.object(preview.os, "geteuid", return_value=0), \
                     patch.object(preview.backend, "prepare_target") as holder:
                    with self.assertRaises(protocol.Refused):
                        preview.preview_request(wire(bad))
                    holder.assert_not_called()

    def test_request_closes_held_context_and_returns_no_authorization(self):
        held = held_target()
        with patch.object(preview.os, "geteuid", return_value=0), \
             patch.object(preview.backend, "prepare_target",
                          return_value=nullcontext(held)) as prep, \
             patch.object(preview.identity, "probe", return_value={}), \
             patch.object(preview.identity, "verify"), \
             patch.object(preview.guard, "privileged_preflight",
                          return_value=PROOF), \
             patch.object(held, "_fresh_device"):
            doc = preview.preview_request(wire())
        prep.assert_called_once_with(
            REVIEW, "ERASE " + DISK,
            username="testpilot", hostname="edos-installed",
        )
        self.assertEqual(doc["status"], "preview-read-only")
        self.assertIs(doc["authorization_to_write"], False)

    def test_refusal_response_redacts_identity_and_exposes_no_writer(self):
        output = io.StringIO()
        with patch.object(preview.os, "geteuid", return_value=0), \
             patch.object(preview.backend, "prepare_target",
                          side_effect=backend.Refused(
                              "Sensitive by-id " + DISK
                          )):
            code = preview.main([], input_stream=wire(), output_stream=output)
        self.assertEqual(code, 2)
        reply = json.loads(output.getvalue())
        self.assertEqual(reply["status"], "refused")
        self.assertFalse(reply["authorization_to_write"])
        self.assertNotIn(DISK, output.getvalue())
        self.assertNotIn("testpilot", output.getvalue())
        self.assertNotIn("Sensitive", output.getvalue())
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_no_physical_executor_in_preview_module(self):
        for name in ("execute", "format_disk", "install", "write_disk",
                     "mount", "run_disko", "stage_account", "run"):
            self.assertFalse(hasattr(preview, name))


if __name__ == "__main__":
    unittest.main()
