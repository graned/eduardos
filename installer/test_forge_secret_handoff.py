"""In-memory / Linux-memfd tests for future sealed credential handoff.

No root, process spawning, disk formatting or permanent credential files.
"""
from __future__ import annotations

import fcntl
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import forge_credentials as credentials
import forge_secret_handoff as handoff


LUKS = "disposable-luks-secret-35-foo"
ACCOUNT = "disposable-account-secret-35-bar"


class SecretHandoffTests(unittest.TestCase):
    def test_separate_sealed_roles_and_consumption(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            self.assertNotEqual(fds.luks, fds.account)
            self.assertEqual(
                os.readlink(f"/proc/self/fd/{fds.luks}"),
                f"/memfd:{credentials.LUKS_MEMFD_LABEL} (deleted)",
            )
            self.assertEqual(
                os.readlink(f"/proc/self/fd/{fds.account}"),
                f"/memfd:{credentials.ACCOUNT_MEMFD_LABEL} (deleted)",
            )
            for fd in (fds.luks, fds.account):
                self.assertTrue(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
                self.assertEqual(
                    fcntl.fcntl(fd, fcntl.F_GET_SEALS) & handoff._REQUIRED_SEALS,
                    handoff._REQUIRED_SEALS,
                )
                with self.assertRaises(OSError):
                    os.write(fd, b"tamper")
            reader = handoff.OneShotCredentialReader(fds)
            with reader.consume() as secrets:
                self.assertEqual(bytes(secrets.luks), LUKS.encode())
                self.assertEqual(bytes(secrets.account), ACCOUNT.encode())
                self.assertIsInstance(secrets.luks, bytearray)
                self.assertIsInstance(secrets.account, bytearray)
            self.assertEqual(bytes(secrets.luks), bytes(len(LUKS)))
            self.assertEqual(bytes(secrets.account), bytes(len(ACCOUNT)))
            with self.assertRaisesRegex(handoff.Refused, "consumed"):
                with reader.consume():
                    pass
        for fd in (fds.luks, fds.account):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_fd_offset_unchanged_by_preadv(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            os.lseek(fds.luks, 4, os.SEEK_SET)
            os.lseek(fds.account, 7, os.SEEK_SET)
            with handoff.OneShotCredentialReader(fds).consume() as material:
                self.assertEqual(bytes(material.luks), LUKS.encode())
                self.assertEqual(bytes(material.account), ACCOUNT.encode())
            self.assertEqual(os.lseek(fds.luks, 0, os.SEEK_CUR), 4)
            self.assertEqual(os.lseek(fds.account, 0, os.SEEK_CUR), 7)

    def test_unrecognized_fd_types_and_swapped_roles_rejected(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            cases = [
                handoff.CredentialFDs(luks=fds.account, account=fds.luks),
                handoff.CredentialFDs(luks=fds.luks, account=fds.luks),
                handoff.CredentialFDs(luks=True, account=fds.account),
                handoff.CredentialFDs(luks=-1, account=fds.account),
                handoff.CredentialFDs(luks="3", account=fds.account),
                handoff.CredentialFDs(luks=fds.luks, account=None),
            ]
            for handles in cases:
                with self.subTest(handles=handles):
                    with self.assertRaises(handoff.Refused):
                        with handoff.OneShotCredentialReader(handles).consume():
                            pass
        with self.assertRaises(handoff.Refused):
            handoff.OneShotCredentialReader((3, 4))

    def test_plain_regular_file_cannot_substitute_a_memfd(self):
        with tempfile.TemporaryFile() as file:
            file.write(LUKS.encode())
            file.flush()
            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
                with self.assertRaises(handoff.Refused):
                    with handoff.OneShotCredentialReader(
                        handoff.CredentialFDs(file.fileno(), fds.account)
                    ).consume():
                        pass

    def test_unsealed_memfd_rejected(self):
        fd = os.memfd_create(
            credentials.LUKS_MEMFD_LABEL,
            os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
        )
        try:
            os.write(fd, LUKS.encode())
            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as pair:
                with self.assertRaisesRegex(handoff.Refused, "sealed"):
                    with handoff.OneShotCredentialReader(
                        handoff.CredentialFDs(fd, pair.account)
                    ).consume():
                        pass
        finally:
            os.close(fd)

    def test_overlarge_memfd_rejected_before_allocation(self):
        fd = os.memfd_create(
            credentials.LUKS_MEMFD_LABEL,
            os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
        )
        try:
            os.ftruncate(fd, handoff._MAX_SECRET_BYTES + 1)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS, handoff._REQUIRED_SEALS)
            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as pair:
                with self.assertRaises(handoff.Refused):
                    with handoff.OneShotCredentialReader(
                        handoff.CredentialFDs(fd, pair.account)
                    ).consume():
                        pass
        finally:
            os.close(fd)

    def test_cloexec_required(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            flags = fcntl.fcntl(fds.luks, fcntl.F_GETFD)
            try:
                fcntl.fcntl(fds.luks, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
                with self.assertRaisesRegex(handoff.Refused, "sealed role"):
                    with handoff.OneShotCredentialReader(fds).consume():
                        pass
            finally:
                fcntl.fcntl(fds.luks, fcntl.F_SETFD, flags)

    def test_missing_fd_rejected(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            saved = os.dup(fds.luks)
            os.close(fds.luks)
            try:
                with self.assertRaises(handoff.Refused):
                    with handoff.OneShotCredentialReader(fds).consume():
                        pass
            finally:
                # Restore descriptor before the producer context closes it.
                os.dup2(saved, fds.luks)
                os.close(saved)

    def test_secret_validation_rejects_bad_text(self):
        for invalid in ("short", "line\ninjection-passphrase", "contains\x00nul-passphrase"):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(credentials.Refused):
                    with handoff.sealed_credential_pair(invalid, ACCOUNT):
                        pass
                with self.assertRaises(credentials.Refused):
                    with handoff.sealed_credential_pair(LUKS, invalid):
                        pass

    def test_short_read_fails_without_leaking_buffer(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            with patch.object(handoff.os, "preadv", return_value=0):
                reader = handoff.OneShotCredentialReader(fds)
                with self.assertRaisesRegex(handoff.Refused, "changed"):
                    with reader.consume():
                        pass
                with self.assertRaisesRegex(handoff.Refused, "consumed"):
                    with reader.consume():
                        pass

    def test_failure_on_second_secret_wipes_first(self):
        first = bytearray(LUKS.encode())
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            with patch.object(handoff, "_read_secret", side_effect=[
                first, handoff.Refused("account password failed"),
            ]):
                with self.assertRaises(handoff.Refused):
                    with handoff.OneShotCredentialReader(fds).consume():
                        pass
        self.assertEqual(bytes(first), bytes(len(LUKS)))

    def test_unauthorized_interface_is_not_a_root_installer(self):
        for prohibited in (
            "main", "install", "format_disk", "mount", "run_disko",
            "grant_root", "authorize_disk", "create_socket", "execute",
        ):
            self.assertFalse(hasattr(handoff, prohibited))


if __name__ == "__main__":
    unittest.main()
