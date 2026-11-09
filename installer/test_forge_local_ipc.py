"""Real Linux AF_UNIX/SO_PEERCRED/SCM_RIGHTS boundary tests, no root.

Only ephemeral sockets and sealed fixture memfds are used. No NixOS
installation, disk writes, privilege escalation or persistent daemon.
"""
from __future__ import annotations

from array import array
import os
import socket
import subprocess
import sys
import tempfile
import unittest

import forge_local_ipc as ipc
import forge_secret_handoff as handoff


LUKS = "public-qemu-luks-test-passphrase-36"
ACCOUNT = "public-qemu-account-test-password-36"


class LocalTransportTests(unittest.TestCase):
    def setUp(self):
        self.client, self.server = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_SEQPACKET,
        )
        self.addCleanup(self.client.close)
        self.addCleanup(self.server.close)
        self.peer = ipc.PeerIdentity(os.getpid(), os.getuid(), os.getgid())

    def send_raw(self, frame, fds):
        payload = array("i", fds).tobytes()
        self.client.sendmsg(
            [frame],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, payload)] if fds else [],
        )

    def test_round_trip_secrets_are_not_serialized(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            existing = len(os.listdir("/proc/self/fd"))
            sender = ipc.OneShotLocalSender(self.client, self.peer)
            receiver = ipc.OneShotLocalReceiver(self.server, self.peer)
            sender.send(fds)
            with self.assertRaisesRegex(ipc.Refused, "consumed"):
                sender.send(fds)
            with receiver.consume() as values:
                self.assertEqual(bytes(values.luks), LUKS.encode())
                self.assertEqual(bytes(values.account), ACCOUNT.encode())
                self.assertNotEqual(values.luks, values.account)
            self.assertEqual(bytes(values.luks), bytes(len(LUKS)))
            self.assertEqual(bytes(values.account), bytes(len(ACCOUNT)))
            with self.assertRaisesRegex(ipc.Refused, "consumed"):
                with receiver.consume():
                    pass
            self.assertEqual(len(os.listdir("/proc/self/fd")), existing)

    def test_unexpected_peer_refused_on_both_sides(self):
        foreign = ipc.PeerIdentity(self.peer.pid, self.peer.uid + 1, self.peer.gid)
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            sender = ipc.OneShotLocalSender(self.client, foreign)
            with self.assertRaisesRegex(ipc.Refused, "allowlist"):
                sender.send(fds)
            with self.assertRaisesRegex(ipc.Refused, "consumed"):
                sender.send(fds)
            # A genuine fixed frame is still refused before the receiver
            # reads a byte or accepts a passed descriptor.
            self.send_raw(ipc.PROTOCOL_MARKER, (fds.luks, fds.account))
            receiver = ipc.OneShotLocalReceiver(self.server, foreign)
            with self.assertRaisesRegex(ipc.Refused, "allowlist"):
                with receiver.consume():
                    pass
            with self.assertRaisesRegex(ipc.Refused, "consumed"):
                with receiver.consume():
                    pass

    def test_expected_peer_must_be_explicit_and_well_formed(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            for expected in (None, "any-user", {"uid": 0}):
                with self.subTest(expected=expected):
                    with self.assertRaisesRegex(ipc.Refused, "mandatory"):
                        ipc.OneShotLocalSender(self.client, expected).send(fds)
        for bad in (
            (0, 0, 0), (-1, 0, 0),
            (os.getpid(), -1, 0), (os.getpid(), 0, -1),
            (True, 0, 0), (os.getpid(), False, 0),
        ):
            with self.subTest(identity=bad), self.assertRaises(ipc.Refused):
                ipc.PeerIdentity(*bad)

    def test_stream_or_tcp_transport_is_forbidden(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        with a, b:
            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
                with self.assertRaisesRegex(ipc.Refused, "seqpacket"):
                    ipc.OneShotLocalSender(a, self.peer).send(fds)
                with self.assertRaisesRegex(ipc.Refused, "seqpacket"):
                    with ipc.OneShotLocalReceiver(b, self.peer).consume():
                        pass

    def test_malformed_frames_close_all_received_descriptors(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            before = len(os.listdir("/proc/self/fd"))
            cases = [
                (b"invalid-header", [fds.luks, fds.account]),
                (ipc.PROTOCOL_MARKER + b"!", [fds.luks, fds.account]),
                (ipc.PROTOCOL_MARKER, []),
                (ipc.PROTOCOL_MARKER, [fds.luks]),
                (ipc.PROTOCOL_MARKER, [fds.luks, fds.account, fds.luks]),
                (ipc.PROTOCOL_MARKER, [fds.account, fds.luks]),
                (ipc.PROTOCOL_MARKER, [fds.luks, fds.luks]),
            ]
            for frame, sent in cases:
                with self.subTest(frame=frame, count=len(sent)):
                    self.send_raw(frame, sent)
                    receiver = ipc.OneShotLocalReceiver(self.server, self.peer)
                    with self.assertRaises((ipc.Refused, handoff.Refused)):
                        with receiver.consume():
                            pass
                    self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_truncated_rights_do_not_leak(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            before = len(os.listdir("/proc/self/fd"))
            self.send_raw(ipc.PROTOCOL_MARKER, [fds.luks] * 32)
            with self.assertRaisesRegex(ipc.Refused, "frame"):
                with ipc.OneShotLocalReceiver(self.server, self.peer).consume():
                    pass
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_received_fd_and_secret_cleanup_on_consumer_exception(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            before = len(os.listdir("/proc/self/fd"))
            ipc.OneShotLocalSender(self.client, self.peer).send(fds)
            with self.assertRaisesRegex(RuntimeError, "consumer crashed"):
                with ipc.OneShotLocalReceiver(self.server, self.peer).consume() as values:
                    raise RuntimeError("consumer crashed")
            self.assertEqual(bytes(values.luks), bytes(len(LUKS)))
            self.assertEqual(bytes(values.account), bytes(len(ACCOUNT)))
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_sender_rejects_wrong_fd_role_before_sending(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            for invalid in (
                handoff.CredentialFDs(fds.account, fds.luks),
                handoff.CredentialFDs(fds.luks, fds.luks),
                handoff.CredentialFDs(-1, fds.account),
            ):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ipc.Refused):
                        ipc.OneShotLocalSender(self.client, self.peer).send(invalid)

    def test_real_distinct_process_peercred(self):
        # The kernel, not a message field, reports the connecting child's PID.
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "forge-test.sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
                listener.bind(path)
                os.chmod(path, 0o600)
                listener.listen(1)
                listener.settimeout(5)
                script = (
                    "import socket,sys; "
                    "s=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET); "
                    "s.connect(sys.argv[1]); s.recv(1); s.close()"
                )
                child = subprocess.Popen(
                    [sys.executable, "-c", script, path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                try:
                    with listener.accept()[0] as connected:
                        self.assertNotEqual(child.pid, os.getpid())
                        expected = ipc.PeerIdentity(
                            child.pid, os.getuid(), os.getgid(),
                        )
                        ipc._verify_peer(connected, expected)
                        with self.assertRaisesRegex(ipc.Refused, "allowlist"):
                            ipc._verify_peer(connected, self.peer)
                        connected.send(b"x")
                    _, stderr = child.communicate(timeout=5)
                    self.assertEqual(child.returncode, 0, stderr.decode())
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.communicate()

    def test_cross_process_both_credential_fds_and_kernel_identity(self):
        # Actual AF_UNIX connect happens AFTER fork: SO_PEERCRED pins the
        # sending child's PID, not merely the creator of a socketpair.
        # Public fixtures live in test source, never subprocess argv/env.
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "forge-credentials-test.sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
                listener.bind(path)
                os.chmod(path, 0o600)
                listener.listen(1)
                listener.settimeout(5)
                parent_pid = os.getpid()
                child_pid = os.fork()
                if child_pid == 0:
                    try:
                        listener.close()
                        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
                            client.connect(path)
                            expected_parent = ipc.PeerIdentity(
                                parent_pid, os.getuid(), os.getgid(),
                            )
                            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as pair:
                                ipc.OneShotLocalSender(client, expected_parent).send(pair)
                    except BaseException:
                        os._exit(42)
                    os._exit(0)
                try:
                    with listener.accept()[0] as conn:
                        expected_child = ipc.PeerIdentity(
                            child_pid, os.getuid(), os.getgid(),
                        )
                        with ipc.OneShotLocalReceiver(conn, expected_child).consume() as material:
                            self.assertEqual(bytes(material.luks), LUKS.encode())
                            self.assertEqual(bytes(material.account), ACCOUNT.encode())
                        self.assertEqual(bytes(material.luks), bytes(len(LUKS)))
                        self.assertEqual(bytes(material.account), bytes(len(ACCOUNT)))
                finally:
                    _, status = os.waitpid(child_pid, 0)
                self.assertTrue(os.WIFEXITED(status))
                self.assertEqual(os.WEXITSTATUS(status), 0)

    def test_no_privileged_install_or_network_listener(self):
        for name in (
            "main", "serve", "bind", "listen", "accept",
            "install", "format_disk", "erase", "mount",
            "polkit", "sudo", "grant_root",
        ):
            self.assertFalse(hasattr(ipc, name))


if __name__ == "__main__":
    unittest.main()
