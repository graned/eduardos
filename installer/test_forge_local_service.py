"""No-disk, no-root tests of PR #37 trusted local preflight policy.

Real AF_UNIX SOCK_SEQPACKET frames are used. Root identity and the
physical disk backend are stubbed; the read-only backend is tested
separately by existing PR #33 fixtures.
"""
from __future__ import annotations

from array import array
from contextlib import contextmanager
import copy
import io
import json
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

import forge_disk_identity as identity
import forge_local_ipc as ipc
import forge_local_service as local
import forge_privileged_protocol as protocol
import forge_secret_handoff as secrets
import forge_socket_lifecycle as lifecycle


DISK = "/dev/disk/by-id/wwn-edos-fixture"
BOOT_ID = "01234567-89ab-cdef-0123-456789abcdef"
DEVICE = {field: None for field in identity.FIELDS}
DEVICE.update({"path": "/dev/vdb", "size": 64 * 1024**3, "maj:min": "8:16"})
SNAPSHOT = {
    "schema": identity.SCHEMA,
    "boot_id": BOOT_ID,
    "stable_id": DISK,
    "device": DEVICE,
    "layout": [],
    "eligible": True,
    "blockers": [],
}
REVIEW = {
    "snapshot": SNAPSHOT,
    "sha256": identity.fingerprint(SNAPSHOT),
    "write_operations_enabled": False,
}
REQUEST = {
    "version": protocol.SCHEMA,
    "operation": "attest-target",
    "review": REVIEW,
    "confirmation": "ERASE " + DISK,
    "username": "testpilot",
    "hostname": "edos-installed",
}
GOOD = {
    "version": protocol.SCHEMA,
    "status": "attested-read-only",
    "write_operations_enabled": False,
    "destructive_disk_operations_enabled": False,
    "credential_writes_enabled": False,
    "authorization_to_write": False,
}


class Clock:
    def __init__(self):
        self.current = 0.0

    def __call__(self):
        return self.current


class PreflightSessionTests(unittest.TestCase):
    def setUp(self):
        self.client, self.server = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_SEQPACKET,
        )
        self.addCleanup(self.client.close)
        self.addCleanup(self.server.close)
        self.peer = ipc.PeerIdentity(os.getpid(), os.getuid(), os.getgid())
        self.clock = Clock()
        self.consents = []

    def approve(self, phrase):
        self.consents.append(phrase)
        return phrase

    def session(self, **overrides):
        kwargs = dict(
            peer=self.peer, review=copy.deepcopy(REVIEW),
            username="testpilot", hostname="edos-installed",
            local_consent=self.approve, clock=self.clock,
        )
        kwargs.update(overrides)
        return local.TrustedIntent(**kwargs)

    def send(self, request=None):
        self.client.send(json.dumps(
            REQUEST if request is None else request, separators=(",", ":"),
        ).encode())

    def process(self, session=None):
        with patch.object(local.os, "geteuid", return_value=0), \
             patch.object(local.identity, "boot_id", return_value=BOOT_ID), \
             patch.object(local.protocol, "handle_request",
                          return_value=GOOD) as preflight:
            ok = local.serve_one_connected(
                self.server, self.session() if session is None else session,
            )
        response = json.loads(self.client.recv(4096))
        return ok, response, preflight

    def test_success_has_exact_review_user_and_local_consent_binding(self):
        self.send()
        ok, report, preflight = self.process()
        self.assertTrue(ok)
        self.assertEqual(report["status"], "attested-read-only")
        preflight.assert_called_once()
        self.assertEqual(
            json.loads(preflight.call_args.args[0].read()), REQUEST,
        )
        self.assertEqual(self.consents, ["ERASE " + DISK])
        self.assertIs(report["authorization_to_write"], False)

    def test_changed_review_username_or_disk_is_denied(self):
        for name, edit in (
            ("username", lambda x: x.update(username="intruder")),
            ("hostname", lambda x: x.update(hostname="other")),
            ("disk", lambda x: x["review"]["snapshot"].update(
                stable_id="/dev/disk/by-id/wwn-other",
            )),
            ("digest", lambda x: x["review"].update(sha256="f" * 64)),
        ):
            with self.subTest(name=name):
                candidate = copy.deepcopy(REQUEST)
                edit(candidate)
                self.send(candidate)
                ok, report, preflight = self.process()
                self.assertFalse(ok)
                self.assertEqual(report["status"], "refused")
                preflight.assert_not_called()
                self.assertNotIn(DISK, json.dumps(report))
                self.assertFalse(report["write_operations_enabled"])

    def test_invalid_authorization_peer_blocks_even_local_consent(self):
        foreign = ipc.PeerIdentity(self.peer.pid, self.peer.uid + 1, self.peer.gid)
        self.send()
        ok, report, preflight = self.process(self.session(peer=foreign))
        self.assertFalse(ok)
        self.assertEqual(report["status"], "refused")
        self.assertFalse(self.consents)
        preflight.assert_not_called()

    def test_wrong_local_consent_never_calls_privileged_preflight(self):
        self.send()
        ok, report, preflight = self.process(
            self.session(local_consent=lambda phrase: "yes"),
        )
        self.assertFalse(ok)
        self.assertEqual(report["status"], "refused")
        preflight.assert_not_called()

    def test_nonroot_rejected_before_consent_or_preflight(self):
        self.send()
        s = self.session()
        with patch.object(local.os, "geteuid", return_value=1000), \
             patch.object(local.protocol, "handle_request") as preflight:
            ok = local.serve_one_connected(self.server, s)
        self.assertFalse(ok)
        preflight.assert_not_called()
        self.assertFalse(self.consents)
        self.assertFalse(s.used is False)
        self.assertEqual(json.loads(self.client.recv(4096))["status"], "refused")

    def test_expired_session_and_boot_swap_fail_before_consent(self):
        self.send()
        s = self.session()
        self.clock.current = local.CONSENT_TTL_SECONDS
        ok, report, preflight = self.process(s)
        self.assertFalse(ok)
        self.assertFalse(self.consents)
        preflight.assert_not_called()
        self.assertEqual(report["status"], "refused")

        # Fresh socket pair for independent swapped-boot check.
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with a, b:
            a.send(json.dumps(REQUEST).encode())
            s2 = self.session()
            with patch.object(local.os, "geteuid", return_value=0), \
                 patch.object(local.identity, "boot_id", return_value="other"), \
                 patch.object(local.protocol, "handle_request") as preflight2:
                ok2 = local.serve_one_connected(b, s2)
            self.assertFalse(ok2)
            preflight2.assert_not_called()
            self.assertEqual(json.loads(a.recv(4096))["status"], "refused")

    def test_one_attempt_cannot_be_replayed(self):
        self.send()
        intent = self.session()
        ok, report, preflight = self.process(intent)
        self.assertTrue(ok)
        self.send()
        ok2, report2, preflight2 = self.process(intent)
        self.assertFalse(ok2)
        self.assertEqual(report2["status"], "refused")
        preflight2.assert_not_called()

    def test_unknown_execution_operation_is_rejected(self):
        candidate = copy.deepcopy(REQUEST)
        candidate["operation"] = "format-disk"
        self.send(candidate)
        ok, report, preflight = self.process()
        self.assertFalse(ok)
        self.assertEqual(report["status"], "refused")
        preflight.assert_not_called()

    def test_fds_in_readonly_attestation_packet_are_closed_and_refused(self):
        with secrets.sealed_credential_pair(
            "disposable-luks-phrase-37", "disposable-account-phrase-37",
        ) as fds:
            before = len(os.listdir("/proc/self/fd"))
            self.client.sendmsg(
                [json.dumps(REQUEST).encode()],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                  array("i", [fds.luks, fds.account]).tobytes())],
            )
            ok, report, preflight = self.process()
            self.assertFalse(ok)
            self.assertEqual(report["status"], "refused")
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)
            preflight.assert_not_called()

    def test_forged_or_oversized_request_is_refused(self):
        self.client.send(b"x" * (local.MAX_PACKET + 1))
        ok, report, preflight = self.process()
        self.assertFalse(ok)
        preflight.assert_not_called()
        self.assertEqual(report["status"], "refused")

    def test_constructor_rejects_bad_trusted_review_and_identity(self):
        bad_review = copy.deepcopy(REVIEW)
        bad_review["sha256"] = "0" * 64
        for changes in (
            {"review": bad_review},
            {"peer": "root"},
            {"username": "forge"},
            {"hostname": "INVALID.HOST"},
            {"local_consent": "yes"},
        ):
            with self.subTest(fields=changes), self.assertRaises(local.Refused):
                self.session(**changes)


class SocketLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = self.tmp.name
        self.owner = os.getuid()
        os.chmod(self.parent, 0o700)

    @property
    def path(self):
        return os.path.join(self.parent, lifecycle.SOCKET_NAME)

    def test_private_socket_mode_and_exact_inode_cleanup(self):
        with lifecycle._private_listener(self.parent, self.owner) as sock:
            self.assertEqual(sock.family, socket.AF_UNIX)
            self.assertEqual(sock.getsockopt(
                socket.SOL_SOCKET, socket.SO_TYPE,
            ), socket.SOCK_SEQPACKET)
            meta = os.lstat(self.path)
            self.assertEqual(meta.st_uid, self.owner)
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.lexists(self.path))

    def test_socket_wont_unlink_existing_path_or_symlink(self):
        with open(self.path, "w", encoding="utf8") as stream:
            stream.write("keep")
        with self.assertRaisesRegex(lifecycle.Refused, "already exists"):
            with lifecycle._private_listener(self.parent, self.owner):
                pass
        with open(self.path, encoding="utf8") as stream:
            self.assertEqual(stream.read(), "keep")
        os.unlink(self.path)
        os.symlink("/tmp", self.path)
        with self.assertRaisesRegex(lifecycle.Refused, "already exists"):
            with lifecycle._private_listener(self.parent, self.owner):
                pass
        self.assertTrue(os.path.islink(self.path))

    def test_group_writable_or_symlinked_parent_refused(self):
        os.chmod(self.parent, 0o770)
        with self.assertRaisesRegex(lifecycle.Refused, "unsafe"):
            with lifecycle._private_listener(self.parent, self.owner):
                pass
        os.chmod(self.parent, 0o700)
        link = self.parent + "-alias"
        os.symlink(self.parent, link)
        self.addCleanup(lambda: os.unlink(link))
        with self.assertRaises(OSError):
            with lifecycle._private_listener(link, self.owner):
                pass

    def test_replaced_socket_inode_is_not_deleted(self):
        with lifecycle._private_listener(self.parent, self.owner):
            os.unlink(self.path)
            with open(self.path, "w", encoding="utf8") as stream:
                stream.write("replacement")
        with open(self.path, encoding="utf8") as stream:
            self.assertEqual(stream.read(), "replacement")

    def test_root_listener_refuses_nonroot_and_has_fixed_path(self):
        with patch.object(lifecycle.os, "geteuid", return_value=1000), \
             self.assertRaisesRegex(lifecycle.Refused, "Only root"):
            with lifecycle.root_listener():
                pass
        self.assertEqual(lifecycle.RUNTIME_DIR, "/run/eduardos")
        self.assertEqual(lifecycle.SOCKET_NAME, "forge-preflight.sock")


if __name__ == "__main__":
    unittest.main()
