"""No-root/no-disk safety tests for PR #38 operator-attested preflight.

Virtual-console ioctls and TTY IO are mocked; the actual root-owned
socket and disk verification remain covered by existing dedicated checks.
"""
from __future__ import annotations

from contextlib import nullcontext
import copy
import io
import os
import socket
import stat
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import forge_console_consent as console
import forge_console_service as service
import forge_disk_identity as identity
import forge_local_ipc as ipc


DISK = "/dev/disk/by-id/wwn-virtual-console-fixture"
BOOT = "01234567-89ab-cdef-0123-456789abcdef"
DEVICE = {key: None for key in identity.FIELDS}
DEVICE.update({"path": "/dev/vdb", "size": 64 * 1024**3, "maj:min": "8:16"})
SNAPSHOT = {
    "schema": identity.SCHEMA, "boot_id": BOOT, "stable_id": DISK,
    "device": DEVICE, "layout": [], "eligible": True, "blockers": [],
}
REVIEW = {
    "snapshot": SNAPSHOT,
    "sha256": identity.fingerprint(SNAPSHOT),
    "write_operations_enabled": False,
}


class ConsolePolicyTests(unittest.TestCase):
    def _vt(self, *, active=2, foreground=True, char=True, root=True):
        dev = SimpleNamespace(
            st_mode=(stat.S_IFCHR if char else stat.S_IFREG) | 0o600,
            st_dev=81, st_ino=1001, st_rdev=os.makedev(4, 2),
        )
        return (
            patch.object(console.os, "geteuid", return_value=0 if root else 1000),
            patch.object(console.os, "fstat", return_value=dev),
            patch.object(console.os, "lstat", return_value=dev),
            patch.object(console.fcntl, "ioctl",
                         return_value=struct.pack("=HHH", active, 0, 0)),
            patch.object(console.os, "tcgetpgrp",
                         return_value=999 if foreground else 998),
            patch.object(console.os, "getpgrp", return_value=999),
        )

    def test_real_vt_identity_and_foreground_only(self):
        import contextlib
        with contextlib.ExitStack() as stack:
            for p in self._vt():
                stack.enter_context(p)
            console.validate_console(71, "/dev/tty2")

    def test_vt_refuses_remote_pty_inactive_nonforeground_and_nonroot(self):
        import contextlib
        scenarios = [
            ({"active": 3}, "/dev/tty2"),
            ({"foreground": False}, "/dev/tty2"),
            ({"char": False}, "/dev/tty2"),
            ({"root": False}, "/dev/tty2"),
            ({}, "/dev/pts/2"),
            ({}, "/dev/tty0"),
            ({}, "/dev/tty64"),
            ({}, "/dev/tty2/../tty3"),
        ]
        for config, name in scenarios:
            with self.subTest(config=config, name=name):
                with contextlib.ExitStack() as stack:
                    for p in self._vt(**config):
                        stack.enter_context(p)
                    with self.assertRaises(console.Refused):
                        console.validate_console(71, name)

    def test_exact_typed_challenge_and_tty_cleanup(self):
        challenge = "ERASE " + DISK
        stream = iter(bytes([b]) for b in challenge.encode() + b"\n")
        tty_attr = [1, 2, 3, console.termios.ECHO | 0x3, 5, 6, []]
        with patch.object(console.os, "geteuid", return_value=0), \
             patch.object(console.os, "open", return_value=71) as opener, \
             patch.object(console.os, "close") as closer, \
             patch.object(console, "validate_console") as check, \
             patch.object(console.termios, "tcgetattr", return_value=tty_attr), \
             patch.object(console.termios, "tcsetattr") as set_attrs, \
             patch.object(console.select, "select", return_value=([71], [], [])), \
             patch.object(console.os, "read", side_effect=stream), \
             patch.object(console.os, "write", side_effect=lambda fd, b: len(b)) as out:
            typed = console.request_local_consent(challenge, "/dev/tty2")
        self.assertEqual(typed, challenge)
        opener.assert_called_once_with("/dev/tty2", console._FLAGS)
        closer.assert_called_once_with(71)
        self.assertEqual(check.call_count, 2)
        self.assertEqual(set_attrs.call_count, 2)
        self.assertEqual(set_attrs.call_args.args[2], tty_attr)
        self.assertNotEqual(set_attrs.call_args_list[0].args[2][3] & console.termios.ECHO,
                            console.termios.ECHO)
        self.assertTrue(any(challenge.encode() in call.args[1]
                            for call in out.call_args_list))

    def test_consent_timeout_restores_terminal_and_closes_fd(self):
        challenge = "ERASE " + DISK
        tty_attr = [1, 2, 3, console.termios.ECHO, 5, 6, []]
        with patch.object(console.os, "geteuid", return_value=0), \
             patch.object(console.os, "open", return_value=71), \
             patch.object(console.os, "close") as closer, \
             patch.object(console, "validate_console"), \
             patch.object(console.termios, "tcgetattr", return_value=tty_attr), \
             patch.object(console.termios, "tcsetattr") as restore, \
             patch.object(console.select, "select", return_value=([], [], [])), \
             patch.object(console.os, "write", side_effect=lambda fd, b: len(b)):
            with self.assertRaisesRegex(console.Refused, "timed out"):
                console.request_local_consent(challenge, "/dev/tty2")
        self.assertEqual(restore.call_count, 2)
        closer.assert_called_once_with(71)

    def test_never_open_tty_for_invalid_input(self):
        with patch.object(console.os, "open") as opening:
            for path in ("/dev/pts/2", "/tmp/tty2", "/dev/tty0"):
                with self.subTest(path=path), self.assertRaises(console.Refused):
                    console.request_local_consent("ERASE " + DISK, path)
            with self.assertRaises(console.Refused):
                console.request_local_consent("FORMAT EVERYTHING", "/dev/tty2")
            with self.assertRaises(console.Refused):
                console.request_local_consent("ERASE " + DISK, "/dev/tty2", timeout=999)
            opening.assert_not_called()


class OneShotRunnerTests(unittest.TestCase):
    def test_runner_selects_disk_and_client_independently_and_exits(self):
        conn = MagicMock()
        server = MagicMock()
        server.accept.return_value = (conn, None)
        response = []

        def handle(connection, trusted):
            response.append((connection, trusted))
            return True

        with patch.object(service.os, "geteuid", return_value=0), \
             patch.object(service.os, "getpid", return_value=999), \
             patch.object(service.os, "pidfd_open", return_value=71) as pid_open, \
             patch.object(service.os, "close") as fdclose, \
             patch.object(service, "_pidfd_alive", return_value=True) as alive:
            result = service.run_once(
                DISK, "testpilot", "edos-installed", 1234, "/dev/tty2",
                capture=lambda disk: (self.assertEqual(disk, DISK)
                                      or copy.deepcopy(REVIEW)),
                listener=lambda: nullcontext(server),
                prompt=lambda challenge, console: challenge,
                serve=handle,
            )
        self.assertTrue(result)
        pid_open.assert_called_once_with(1234, 0)
        self.assertEqual(alive.call_count, 3)
        fdclose.assert_called_once_with(71)
        server.accept.assert_called_once_with()
        conn.__enter__.assert_called_once()
        conn.__exit__.assert_called_once()
        trusted = response[0][1]
        self.assertEqual(trusted.peer, ipc.PeerIdentity(1234, 0, 0))
        self.assertEqual(trusted.review, REVIEW)
        self.assertEqual(trusted.local_consent("ERASE " + DISK),
                         "ERASE " + DISK)

    def test_root_and_path_gates_before_any_pidfd_or_disk(self):
        with patch.object(service.os, "geteuid", return_value=1000), \
             patch.object(service.os, "pidfd_open") as pidfd:
            with self.assertRaisesRegex(service.Refused, "requires root"):
                service.run_once(DISK, "testpilot", "host",
                                 10, "/dev/tty2")
            pidfd.assert_not_called()
        with patch.object(service.os, "geteuid", return_value=0), \
             patch.object(service.os, "getpid", return_value=7), \
             patch.object(service.os, "pidfd_open") as pidfd:
            cases = [
                ("/dev/sda", 10, "/dev/tty2"),
                (DISK, 7, "/dev/tty2"),
                (DISK, -1, "/dev/tty2"),
                (DISK, 10, "/dev/pts/3"),
            ]
            for disk, pid, tty in cases:
                with self.subTest(disk=disk, pid=pid, tty=tty):
                    with self.assertRaises(service.Refused):
                        service.run_once(disk, "testpilot", "host", pid, tty)
            pidfd.assert_not_called()

    def test_pid_exit_refuses_before_disk_or_after_accept(self):
        server = MagicMock()
        server.accept.return_value = (MagicMock(), None)
        for pattern in ([False], [True, False]):
            with self.subTest(steps=pattern), \
                 patch.object(service.os, "geteuid", return_value=0), \
                 patch.object(service.os, "getpid", return_value=7), \
                 patch.object(service.os, "pidfd_open", return_value=71), \
                 patch.object(service.os, "close") as close, \
                 patch.object(service, "_pidfd_alive", side_effect=pattern), \
                 patch.object(service.identity, "capture",
                              return_value=copy.deepcopy(REVIEW)) as capture, \
                 patch.object(service.lifecycle, "root_listener",
                              return_value=nullcontext(server)), \
                 patch.object(service.local, "serve_one_connected") as serve:
                with self.assertRaisesRegex(service.Refused, "exited|running"):
                    service.run_once(DISK, "testpilot", "host", 1234, "/dev/tty2")
                close.assert_called_once_with(71)
                if not pattern[0]:
                    capture.assert_not_called()
                serve.assert_not_called()

    def test_cli_rejects_failed_trust_without_traceback_or_sensitive_data(self):
        with patch.object(service, "run_once",
                          side_effect=service.Refused("secret internal disk details")), \
             patch.object(service.sys, "stderr", new_callable=io.StringIO) as err:
            code = service.main([
                "--disk-id", DISK, "--username", "testpilot",
                "--hostname", "edos-installed", "--client-pid", "1234",
                "--console", "/dev/tty2",
            ])
        self.assertEqual(code, 2)
        self.assertNotIn(DISK, err.getvalue())
        self.assertNotIn("secret", err.getvalue())

    def test_pidfd_poll_reports_dead_and_live(self):
        with patch.object(service.select, "poll") as constructor:
            constructor.return_value.poll.return_value = []
            self.assertTrue(service._pidfd_alive(71))
            constructor.return_value.poll.return_value = [(71, service.select.POLLHUP)]
            self.assertFalse(service._pidfd_alive(71))


if __name__ == "__main__":
    unittest.main()
