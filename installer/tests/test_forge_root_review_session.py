"""Mock-only final review local protocol tests: no sockets or device I/O."""
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_root_review_session as session


class FakeConn:
    def __init__(self):
        self.response = None
        self.timeout = None
    def gettimeout(self):
        return self.timeout
    def settimeout(self, value):
        self.timeout = value
    def send(self, data):
        self.response = json.loads(data)
        return len(data)


class FakeIntent:
    def __init__(self):
        self.review = {"snapshot": {"boot_id": "boot",
                                    "stable_id": "/dev/disk/by-id/wwn-a"}}
        self.username = "developer"
        self.hostname = "edos"
        self.deadline = 100
        self.used = False
    def clock(self):
        return 1
    def consume(self, conn):
        if self.used:
            raise session.local.Refused("already consumed")
        self.used = True


@contextmanager
def prepared(*args, **kwargs):
    yield SimpleNamespace(devno="8:0")


class RootReviewSessionTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn()
        self.trusted = FakeIntent()
        self.inputs = dict(disko_script="/nix/store/immutable-script",
                           system_closure="/nix/store/immutable-closure")
        self.mocks = [
            mock.patch.object(session.local, "TrustedIntent", FakeIntent),
            mock.patch.object(session.os, "geteuid", return_value=0),
            mock.patch.object(session.identity, "boot_id", return_value="boot"),
            mock.patch.object(session.local, "_receive_request", return_value=b"review"),
            mock.patch.object(session.protocol, "parse_request", return_value=SimpleNamespace(
                review=self.trusted.review, username="developer",
                hostname="edos", confirmation="ERASE /dev/disk/by-id/wwn-a")),
            mock.patch.object(session.backend, "prepare_target", side_effect=prepared),
            mock.patch.object(session.gate, "review_before_execution", return_value={
                "status": "final-review-only", "executable": False,
                "write_operations_enabled": False,
                "destructive_disk_operations_enabled": False,
                "authorization_to_write": False}),
        ]
        for patcher in self.mocks:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_one_shot_read_only_review(self):
        self.assertTrue(session.assess_connected(self.conn, self.trusted, **self.inputs))
        self.assertEqual(self.conn.response["status"], "reviewed-read-only")
        self.assertFalse(self.conn.response["executable"])
        self.assertFalse(self.conn.response["authorization_to_write"])
        self.assertFalse(session.assess_connected(self.conn, self.trusted, **self.inputs))
        self.assertEqual(self.conn.response["status"], "refused")

    def test_mismatched_root_selection_is_refused(self):
        self.trusted.hostname = "different"
        self.assertFalse(session.assess_connected(self.conn, self.trusted, **self.inputs))
        self.assertEqual(self.conn.response["status"], "refused")

    def test_root_and_expiry_required(self):
        with mock.patch.object(session.os, "geteuid", return_value=1000):
            self.assertFalse(session.assess_connected(self.conn, self.trusted, **self.inputs))
        self.trusted = FakeIntent()
        self.trusted.deadline = 0
        self.assertFalse(session.assess_connected(self.conn, self.trusted, **self.inputs))

    def test_cannot_promote_review_into_execution(self):
        with mock.patch.object(session.gate, "review_before_execution", return_value={
            "status": "final-review-only", "executable": True,
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "authorization_to_write": False}):
            self.assertFalse(session.assess_connected(self.conn, self.trusted, **self.inputs))
            self.assertFalse(self.conn.response["executable"])

    def test_unexpected_descriptors_refuse_before_review(self):
        with mock.patch.object(session.local, "_receive_request",
                               side_effect=session.local.Refused("unexpected FDs")):
            self.assertFalse(session.assess_connected(self.conn, self.trusted, **self.inputs))
            self.assertEqual(self.conn.response["status"], "refused")


if __name__ == "__main__":
    unittest.main()
