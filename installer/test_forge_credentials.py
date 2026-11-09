"""Non-destructive credential tests. All filesystem writes use a temp tree."""
from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import forge_credentials as credentials


USERNAME = "testpilot"
PASSWORD = "correct horse battery staple"
LUKS = "demo-luks-passphrase-1234"


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "persist").mkdir(mode=0o755)
        self.uid = os.geteuid()

    def root_fd(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.addCleanup(os.close, fd)
        return fd

    def make_hash(self):
        # In tests, this is only fixture data, never a real user password.
        return "$6$abcdefghijklmnop$" + "a" * 86

    def test_openssl_produces_salted_linux_shadow_hash(self):
        result1 = credentials.hash_user_password(PASSWORD)
        result2 = credentials.hash_user_password(PASSWORD)
        self.assertRegex(result1, r"^\$6\$[A-Za-z0-9./]+\$")
        self.assertTrue(result1.startswith("$6$"))
        self.assertNotEqual(result1, result2)
        # Salt is not secret; verification still supplies password via stdin.
        salt = result1.split("$")[2]
        check = subprocess.run(["openssl", "passwd", "-6", "-salt", salt, "-stdin"],
                               input=(PASSWORD + "\n").encode(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=True)
        self.assertEqual(check.stdout.decode().strip(), result1)

    def test_password_never_goes_in_process_argv(self):
        from types import SimpleNamespace
        fixture = self.make_hash()
        with patch.object(credentials.subprocess, "run",
                          return_value=SimpleNamespace(stdout=(fixture + "\n").encode())) as run:
            self.assertEqual(credentials.hash_user_password(PASSWORD), fixture)
        args = run.call_args.args[0]
        self.assertEqual(args, ["openssl", "passwd", "-6", "-stdin"])
        self.assertNotIn(PASSWORD, repr(args))
        self.assertTrue(run.call_args.kwargs["input"].startswith(PASSWORD.encode()))
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_atomic_create_only_and_private_file(self):
        fd = self.root_fd()
        digest = self.make_hash()
        result = credentials.write_user_hash(fd, USERNAME, digest, expected_uid=self.uid)
        self.assertEqual(result, "/persist/eduardos/credentials/testpilot.hash")
        cred_dir = self.root / "persist" / "eduardos" / "credentials"
        installed = cred_dir / "testpilot.hash"
        self.assertEqual(installed.read_text(), digest + "\n")
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(cred_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(cred_dir.parent.stat().st_mode), 0o700)
        self.assertEqual(installed.stat().st_uid, self.uid)
        self.assertFalse(any(name.suffix == ".tmp" for name in cred_dir.iterdir()))

    def test_refuse_existing_file_without_overwrite(self):
        fd = self.root_fd()
        digest = self.make_hash()
        credentials.write_user_hash(fd, USERNAME, digest, expected_uid=self.uid)
        installed = self.root / "persist/eduardos/credentials/testpilot.hash"
        before = installed.read_bytes()
        with self.assertRaises(FileExistsError):
            credentials.write_user_hash(fd, USERNAME, digest, expected_uid=self.uid)
        self.assertEqual(installed.read_bytes(), before)
        self.assertEqual(sorted(x.name for x in installed.parent.iterdir()),
                         ["testpilot.hash"])

    def test_refuse_existing_symlink_or_permissive_directory(self):
        fd = self.root_fd()
        with self.assertRaises(credentials.Refused):
            credentials.write_user_hash(fd, "root", self.make_hash(), expected_uid=self.uid)
        (self.root / "persist/eduardos").mkdir(mode=0o755)
        with self.assertRaises(credentials.Refused):
            credentials.write_user_hash(fd, USERNAME, self.make_hash(), expected_uid=self.uid)
        (self.root / "persist/eduardos").chmod(0o700)
        (self.root / "persist/eduardos/credentials").mkdir(mode=0o700)
        link = self.root / "persist/eduardos/credentials/testpilot.hash"
        link.symlink_to(self.root / "outside")
        with self.assertRaises(FileExistsError):
            credentials.write_user_hash(fd, USERNAME, self.make_hash(), expected_uid=self.uid)
        self.assertFalse((self.root / "outside").exists())

    def test_refuse_symlinked_persist_mount(self):
        fd = self.root_fd()
        (self.root / "persist").rmdir()
        (self.root / "persist").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            credentials.write_user_hash(fd, USERNAME, self.make_hash(), expected_uid=self.uid)
        self.assertFalse((self.root / "eduardos").exists())

    def test_missing_persist_is_not_silently_created(self):
        fd = self.root_fd()
        (self.root / "persist").rmdir()
        with self.assertRaises(OSError):
            credentials.write_user_hash(fd, USERNAME, self.make_hash(), expected_uid=self.uid)
        self.assertFalse((self.root / "persist").exists())

    def test_refuse_wrong_owner_and_permissive_target(self):
        fd = self.root_fd()
        with self.assertRaises(credentials.Refused):
            credentials.write_user_hash(fd, USERNAME, self.make_hash(),
                                        expected_uid=self.uid + 1)
        os.chmod(self.root / "persist", 0o777)
        with self.assertRaises(credentials.Refused):
            credentials.write_user_hash(fd, USERNAME, self.make_hash(),
                                        expected_uid=self.uid)

    def test_atomic_write_failure_cleans_temporary_file(self):
        fd = self.root_fd()
        with patch.object(credentials.os, "link", side_effect=OSError(errno.ENOSPC, "disk full")):
            with self.assertRaises(OSError):
                credentials.write_user_hash(fd, USERNAME, self.make_hash(),
                                            expected_uid=self.uid)
        path = self.root / "persist/eduardos/credentials"
        self.assertEqual(list(path.iterdir()), [])

    def test_reject_malformed_hash_and_unsafe_username(self):
        fd = self.root_fd()
        for username in ("../../etc", "forge", "root", "BAD", "a" * 40):
            with self.subTest(username=username), self.assertRaises(credentials.Refused):
                credentials.write_user_hash(fd, username, self.make_hash(),
                                            expected_uid=self.uid)
        for malformed in ("plaintext", "$y$not-supported", self.make_hash() + "\n"):
            with self.subTest(malformed=malformed), self.assertRaises(credentials.Refused):
                credentials.write_user_hash(fd, USERNAME, malformed,
                                            expected_uid=self.uid)

    def test_luks_fd_is_sealed_anonymous_and_closed(self):
        with credentials.sealed_luks_fd(LUKS) as fd:
            self.assertEqual(os.read(fd, 4096), LUKS.encode())
            self.assertEqual(os.lseek(fd, 0, os.SEEK_END), len(LUKS.encode()))
            self.assertTrue(fcntl.fcntl(fd, fcntl.F_GET_SEALS) & fcntl.F_SEAL_WRITE)
            with self.assertRaises(OSError):
                os.write(fd, b"tamper")
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_luks_fd_closes_when_consumer_fails(self):
        fd = None
        with self.assertRaisesRegex(RuntimeError, "fake consumer"):
            with credentials.sealed_luks_fd(LUKS) as current:
                fd = current
                raise RuntimeError("fake consumer")
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_luks_rejects_short_and_newline_secrets(self):
        for item in ("short", "longpassphrase\ninjected", "password\0injected"):
            with self.subTest(secret=repr(item)), self.assertRaises(credentials.Refused):
                with credentials.sealed_luks_fd(item):
                    pass

    def test_fd_unavailable_fails_closed(self):
        with patch.object(credentials.os, "memfd_create", side_effect=OSError(errno.ENOSYS, "no memfd")):
            with self.assertRaises(credentials.Refused):
                with credentials.sealed_luks_fd(LUKS):
                    pass

    def test_no_destructive_entrypoint(self):
        for name in ("install", "wipe", "partition", "format_disk", "main"):
            self.assertFalse(hasattr(credentials, name))


if __name__ == "__main__":
    unittest.main()
