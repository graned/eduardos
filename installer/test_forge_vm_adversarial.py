"""Real-root adversarial installer boundary tests, for a disposable NixOS VM.

Unlike ordinary mocked tests, this suite uses REAL uid/gid, forked PIDs,
pidfds, Unix socket path permissions and SO_PEERCRED in the VM kernel.
Only the physical disk attestation response and the independent
physical-console confirmation are simulated: NO disk can be formatted.
Run only in the disposable nixosTest guest as root.
"""
from __future__ import annotations

from array import array
import copy
import json
import os
import socket
import stat
import time
import unittest
from unittest.mock import patch

import forge_console_consent as console
import forge_console_service as runner
import forge_disk_identity as identity
import forge_local_ipc as ipc
import forge_local_service as local
import forge_privileged_protocol as protocol
import forge_secret_handoff as secrets
import forge_socket_lifecycle as lifecycle


DISK = "/dev/disk/by-id/wwn-QEMU-adversarial-fixture-only"
HOST = "edos-disposable"
USER = "testpilot"
LUKS_FIXTURE = "EDOS-QEMU-public-luks-fixture-39"
ACCOUNT_FIXTURE = "EDOS-QEMU-public-account-fixture-39"


def make_review():
    snapshot = {
        "schema": identity.SCHEMA,
        "boot_id": identity.boot_id(),
        "stable_id": DISK,
        "device": {field: None for field in identity.FIELDS},
        "layout": [],
        "eligible": True,
        "blockers": [],
    }
    snapshot["device"].update({
        "path": "/dev/vdb", "size": 64 * 1024**3,
        "maj:min": "8:16",
    })
    return {
        "snapshot": snapshot,
        "sha256": identity.fingerprint(snapshot),
        "write_operations_enabled": False,
    }


def make_message(review):
    return {
        "version": protocol.SCHEMA,
        "operation": protocol.OPERATION,
        "review": review,
        "confirmation": "ERASE " + DISK,
        "username": USER,
        "hostname": HOST,
    }


RESULT = {
    "version": protocol.SCHEMA,
    "status": "attested-read-only",
    "write_operations_enabled": False,
    "destructive_disk_operations_enabled": False,
    "credential_writes_enabled": False,
    "authorization_to_write": False,
}


def _connect_client(path):
    # Connect AFTER fork, or SO_PEERCRED would report the parent's PID.
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    sock.settimeout(6)
    deadline = time.monotonic() + 5
    while True:
        try:
            sock.connect(path)
            return sock
        except (FileNotFoundError, ConnectionRefusedError):
            if time.monotonic() >= deadline:
                sock.close()
                raise
            time.sleep(0.02)


def _child_attack(mode, message, ack_read):
    """Return exit code, keeping child PID alive until server finishes."""
    code = 1
    try:
        with _connect_client(
            lifecycle.RUNTIME_DIR + "/" + lifecycle.SOCKET_NAME
        ) as conn:
            if mode == "fds":
                with secrets.sealed_credential_pair(
                    LUKS_FIXTURE, ACCOUNT_FIXTURE,
                ) as fds:
                    packet = json.dumps(message).encode()
                    conn.sendmsg([packet], [(
                        socket.SOL_SOCKET, socket.SCM_RIGHTS,
                        array("i", [fds.luks, fds.account]).tobytes(),
                    )])
            elif mode == "oversized":
                conn.send(b"x" * (local.MAX_PACKET + 64))
            elif mode == "silent":
                pass
            else:
                conn.send(json.dumps(message).encode())
            response = json.loads(conn.recv(4096))
            if response.get("status") not in (
                "refused", "attested-read-only",
            ):
                return 3
            if (response.get("authorization_to_write") is not False
                    or response.get("write_operations_enabled") is not False
                    or response.get("destructive_disk_operations_enabled") is not False):
                return 4
            expected = ("attested-read-only"
                        if mode in ("valid", "replay") else "refused")
            code = 0 if response["status"] == expected else 5
            if code == 0 and mode == "replay":
                # The server must close this socket after the first
                # request; a second successful preflight is forbidden.
                try:
                    conn.send(json.dumps(message).encode())
                    replay = conn.recv(4096)
                    if replay:
                        code = 7
                except (BrokenPipeError, ConnectionResetError):
                    pass
    except BaseException:
        code = 6
    finally:
        # This keeps our PID pinned and alive through run_once's final
        # pidfd check. Parent releases the child once checks finish.
        try:
            os.read(ack_read, 1)
        except OSError:
            pass
    return code


class RealKernelAdversarialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.geteuid() != 0:
            raise RuntimeError("Run only as root inside disposable NixOS VM")
        os.makedirs(lifecycle.RUNTIME_DIR, mode=0o700, exist_ok=True)
        os.chmod(lifecycle.RUNTIME_DIR, 0o700)

    def setUp(self):
        self.review = make_review()
        self.socket_path = lifecycle.RUNTIME_DIR + "/" + lifecycle.SOCKET_NAME
        self.assertFalse(os.path.lexists(self.socket_path))

    def tearDown(self):
        self.assertFalse(
            os.path.lexists(self.socket_path),
            "A one-shot privileged socket leaked beyond its request",
        )

    def run_case(self, mode="valid", *, message=None, consent=True,
                 expected_success=None, expected_pid=None,
                 timeout_override=None):
        """One real root child connects to a real root-owned socket."""
        if expected_success is None:
            expected_success = (mode in ("valid", "replay") and consent
                                and expected_pid is None)
        request = make_message(self.review) if message is None else message
        rfd, wfd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(wfd)
            try:
                result = _child_attack(mode, request, rfd)
            finally:
                os.close(rfd)
            os._exit(result)
        os.close(rfd)

        approves = []
        def prompt(phrase, selected_console):
            approves.append(phrase)
            self.assertEqual(selected_console, "/dev/tty2")
            return phrase if consent else "NO"

        try:
            with patch.object(
                local.protocol, "handle_request", return_value=RESULT,
            ) as preflight:
                override = (patch.object(ipc, "IO_TIMEOUT_SECONDS",
                                         timeout_override)
                            if timeout_override is not None else None)
                try:
                    if override is not None:
                        override.__enter__()
                    ok = runner.run_once(
                        DISK, USER, HOST,
                        expected_pid if expected_pid is not None else pid,
                        "/dev/tty2",
                        capture=lambda selected: (
                            copy.deepcopy(self.review)
                            if selected == DISK else None
                        ),
                        prompt=prompt,
                        listener=lifecycle.root_listener,
                        serve=local.serve_one_connected,
                    )
                finally:
                    if override is not None:
                        override.__exit__(None, None, None)
                self.assertIs(ok, expected_success)
                if expected_success:
                    preflight.assert_called_once()
                else:
                    preflight.assert_not_called()
        finally:
            os.write(wfd, b"done")
            os.close(wfd)
            child, status = os.waitpid(pid, 0)
            self.assertEqual(child, pid)
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
        return approves

    def test_genuine_root_client_preflight_is_read_only(self):
        consent = self.run_case("valid")
        self.assertEqual(consent, ["ERASE " + DISK])

    def test_one_connection_cannot_replay_preflight(self):
        self.run_case("replay")
    
    def test_different_root_client_pid_is_denied_before_consent(self):
        hold_read, hold_write = os.pipe()
        pinned = os.fork()
        if pinned == 0:
            os.close(hold_write)
            os.read(hold_read, 1)
            os.close(hold_read)
            os._exit(0)
        os.close(hold_read)
        try:
            # Actual sender is a DIFFERENT root child. Even though both
            # UID and GID are zero, the pinned process ID must match.
            approvals = self.run_case(
                "malicious", expected_pid=pinned, expected_success=False,
            )
            self.assertEqual(approvals, [])
        finally:
            os.write(hold_write, b"x")
            os.close(hold_write)
            _, status = os.waitpid(pinned, 0)
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)

    def test_malicious_root_client_wrong_operation(self):
        message = make_message(self.review)
        message["operation"] = "format-disk"
        self.run_case("bad-operation", message=message,
                      expected_success=False)

    def test_root_client_cannot_change_review_or_account(self):
        for attack in ("username", "disk", "digest", "password"):
            with self.subTest(attack=attack):
                packet = make_message(self.review)
                if attack == "username":
                    packet["username"] = "hacker"
                elif attack == "disk":
                    packet["review"] = copy.deepcopy(packet["review"])
                    packet["review"]["snapshot"]["stable_id"] = (
                        "/dev/disk/by-id/wwn-other"
                    )
                elif attack == "digest":
                    packet["review"] = copy.deepcopy(packet["review"])
                    packet["review"]["sha256"] = "f" * 64
                else:
                    packet["luks_passphrase"] = "never allowed here"
                self.run_case("malicious", message=packet,
                              expected_success=False)

    def test_root_client_cannot_inject_sealed_password_fds(self):
        count = len(os.listdir("/proc/self/fd"))
        self.run_case("fds", expected_success=False)
        self.assertEqual(len(os.listdir("/proc/self/fd")), count)

    def test_root_client_packet_truncation_fails_closed(self):
        self.run_case("oversized", expected_success=False)

    def test_root_client_silence_times_out_and_closes_socket(self):
        self.run_case("silent", expected_success=False,
                      timeout_override=0.2)

    def test_wrong_local_console_consent_denies_root_client(self):
        self.assertEqual(
            self.run_case("malicious", consent=False,
                          expected_success=False),
            ["ERASE " + DISK],
        )

    def test_actual_nonroot_process_cannot_enter_root_socket(self):
        with lifecycle.root_listener():
            child = os.fork()
            if child == 0:
                try:
                    os.setgroups([])
                    os.setgid(65534)
                    os.setuid(65534)
                    self.assertEqual(os.geteuid(), 65534)
                    self.assertEqual(os.getegid(), 65534)
                    with socket.socket(
                        socket.AF_UNIX, socket.SOCK_SEQPACKET
                    ) as conn:
                        try:
                            conn.connect(self.socket_path)
                        except PermissionError:
                            os._exit(0)
                        else:
                            os._exit(20)
                except BaseException:
                    os._exit(21)
            _, status = os.waitpid(child, 0)
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
            # A rejected user must not have created any connection.
            self.assertEqual(os.stat(self.socket_path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(lifecycle.RUNTIME_DIR).st_mode & 0o777,
                             0o700)

    def test_dead_client_pidfd_blocks_preflight_before_listener(self):
        child = os.fork()
        if child == 0:
            os._exit(0)
        os.waitpid(child, 0)
        with patch.object(identity, "capture") as review:
            with self.assertRaises(runner.Refused):
                runner.run_once(DISK, USER, HOST, child, "/dev/tty2")
            review.assert_not_called()

    def test_root_pseudo_terminal_has_no_local_consent_authority(self):
        for console_path in ("/dev/pts/0", "/dev/tty0", "/dev/tty64"):
            with self.subTest(path=console_path):
                with self.assertRaises(console.Refused):
                    console.request_local_consent(
                        "ERASE " + DISK, console_path, timeout=0.1,
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
