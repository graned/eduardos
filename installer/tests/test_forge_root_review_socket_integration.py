"""Real Linux AF_UNIX SOCK_SEQPACKET integration for root review (NO disk writes).

The peer identity and receive/send use real kernel sockets. Only block-disk
preparation and final disk policy review are mocked, so these tests cannot
invoke Disko or touch a block device.
"""
from contextlib import contextmanager
from array import array
import json
import os
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_root_review_session as root
import forge_disk_identity as identity
import forge_privileged_protocol as protocol
import forge_local_ipc as ipc
import forge_local_service as local


@contextmanager
def held_target(*args, **kwargs):
    yield SimpleNamespace(devno="8:16")


def trusted_intent():
    snapshot = {
        "schema": identity.SCHEMA,
        "boot_id": identity.boot_id(),
        "stable_id": "/dev/disk/by-id/wwn-0xabcd",
        "device": dict.fromkeys(identity.FIELDS),
        "layout": [],
        "eligible": True,
        "blockers": [],
    }
    review = {
        "snapshot": snapshot,
        "sha256": identity.fingerprint(snapshot),
        "write_operations_enabled": False,
    }
    return local.TrustedIntent(
        peer=ipc.PeerIdentity(os.getpid(), os.getuid(), os.getgid()),
        review=review,
        username="developer",
        hostname="eduardos",
        # Tests simulate a consenting local console; production MUST use a
        # human-operated trusted TTY prompt, never return the phrase itself.
        local_consent=lambda challenge: challenge,
    )


def request_bytes(intent, **change):
    value = {
        "version": protocol.SCHEMA,
        "operation": protocol.OPERATION,
        "review": intent.review,
        "confirmation": "ERASE " + intent.review["snapshot"]["stable_id"],
        "username": intent.username,
        "hostname": intent.hostname,
    }
    value.update(change)
    return json.dumps(value, sort_keys=True).encode()


class RealSocketReviewTests(unittest.TestCase):
    def setUp(self):
        if not hasattr(socket, "SOCK_SEQPACKET") or not hasattr(socket, "SO_PEERCRED"):
            self.skipTest("Linux Unix seqpacket peer credentials required")
        self.server, self.client = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.addCleanup(self.server.close)
        self.addCleanup(self.client.close)
        self.intent = trusted_intent()
        self.fixed = {
            "disko_script": "/nix/store/" + "a"*32 + "-disko/bin/disko",
            "system_closure": "/nix/store/" + "b"*32 + "-nixos-system",
        }

    def execute(self, frame=None, *, ancillary=None, intent=None):
        self.client.sendmsg([request_bytes(self.intent) if frame is None else frame], ancillary or [])
        trusted = self.intent if intent is None else intent
        with mock.patch.object(root.os, "geteuid", return_value=0), \
             mock.patch.object(root.backend, "prepare_target", side_effect=held_target) as prepare, \
             mock.patch.object(root.gate, "review_before_execution", return_value={
                 "status": "final-review-only",
                 "target_devno": "8:16",
                 "executable": False,
                 "write_operations_enabled": False,
                 "destructive_disk_operations_enabled": False,
                 "authorization_to_write": False,
             }) as gate:
            accepted = root.assess_connected(self.server, trusted, **self.fixed)
        reply = json.loads(self.client.recv(2048))
        return accepted, reply, prepare, gate

    def test_real_kernel_peer_and_strict_json_produce_read_only_review(self):
        accepted, reply, prepare, gate = self.execute()
        self.assertTrue(accepted)
        self.assertEqual(reply["status"], "reviewed-read-only")
        self.assertFalse(reply["authorization_to_write"])
        prepare.assert_called_once()
        gate.assert_called_once()

    def test_real_protocol_refuses_mismatched_user(self):
        accepted, reply, prepare, gate = self.execute(
            request_bytes(self.intent, username="attacker"))
        self.assertFalse(accepted)
        self.assertEqual(reply["status"], "refused")
        prepare.assert_not_called()
        gate.assert_not_called()

    def test_replay_refused_after_consuming_trusted_intent(self):
        self.execute()
        accepted, reply, prepare, _ = self.execute()
        self.assertFalse(accepted)
        self.assertEqual(reply["status"], "refused")
        prepare.assert_not_called()

    def test_wrong_kernel_peer_refused_before_disk_preparation(self):
        wrong = trusted_intent()
        wrong.peer = ipc.PeerIdentity(os.getpid() + 100000, os.getuid(), os.getgid())
        accepted, reply, prepare, _ = self.execute(intent=wrong)
        self.assertFalse(accepted)
        self.assertEqual(reply["status"], "refused")
        prepare.assert_not_called()

    def test_passed_descriptor_refused_and_no_disk_preparation(self):
        fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        try:
            frame = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array("i", [fd]).tobytes())]
            accepted, reply, prepare, _ = self.execute(ancillary=frame)
        finally:
            os.close(fd)
        self.assertFalse(accepted)
        self.assertEqual(reply["status"], "refused")
        prepare.assert_not_called()

    def test_truncated_or_non_json_frame_refused(self):
        accepted, reply, prepare, _ = self.execute(b'{"version":')
        self.assertFalse(accepted)
        self.assertEqual(reply["status"], "refused")
        prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
