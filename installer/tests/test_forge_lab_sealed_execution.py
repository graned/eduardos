"""Role-sealed credential acceptance for the actual disposable-QEMU executor.

Read-only synthetic tests. No Disko, no mount/formatter, no root privileges
and no physical block devices. The full destructive test is in QEMU.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_executor_lab as executor
import forge_credentials as credentials
import forge_secret_handoff as handoff
import forge_lab_gui as gui

LUKS = "public-disposable-luks-credential-123"
ACCOUNT = "public-disposable-account-credential-456"


class SealedExecutionContractTests(unittest.TestCase):
    def test_sealed_role_luks_link_accepted_without_creating_plaintext(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "edos-test-passphrase"
            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as pair:
                os.symlink(f"/proc/{os.getpid()}/fd/{pair.luks}", path)
                executor.verify_luks_input(path)
                self.assertTrue(path.is_symlink())
                self.assertEqual(path.lstat().st_size > 0, True)
                self.assertEqual(os.readlink(path),
                                 f"/proc/{os.getpid()}/fd/{pair.luks}")

    def test_swapped_role_rejected_before_any_disk_action(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "edos-test-passphrase"
            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as pair:
                os.symlink(f"/proc/{os.getpid()}/fd/{pair.account}", path)
                with self.assertRaises(executor.Refused):
                    executor.verify_luks_input(path)

    def test_untrusted_symlink_and_other_process_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "edos-test-passphrase"
            with handoff.sealed_credential_pair(LUKS, ACCOUNT) as pair:
                for target in ("/etc/passwd",
                               f"/proc/{os.getpid() + 1}/fd/{pair.luks}",
                               f"/proc/self/fd/{pair.luks}"):
                    with self.subTest(target=target):
                        path.symlink_to(target)
                        with self.assertRaises(executor.Refused):
                            executor.verify_luks_input(path)
                        path.unlink()

    def test_no_unsealed_file_or_short_fixture(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "edos-test-passphrase"
            with self.assertRaises(executor.Refused):
                executor.verify_luks_input(path)
            path.write_bytes(b"short")
            path.chmod(0o600)
            with self.assertRaises(executor.Refused):
                executor.verify_luks_input(path)

    def test_operator_tty_mode_fails_closed_without_root(self):
        with mock.patch.object(gui.os, "geteuid", return_value=1000):
            result = gui.main([
                "--executor", "/nix/store/not-an-executable",
                "--operator-confirm", "ERASE DISPOSABLE /dev/vda",
                "--trusted-console-credentials",
            ])
        self.assertEqual(result, 2)

    def test_pair_consumer_verifies_both_roles(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as pair:
            with handoff.OneShotCredentialReader(pair).consume() as material:
                self.assertEqual(material.luks.decode(), LUKS)
                self.assertEqual(material.account.decode(), ACCOUNT)
            with self.assertRaises(handoff.Refused):
                with handoff.OneShotCredentialReader(
                    handoff.CredentialFDs(pair.account, pair.luks)
                ).consume():
                    pass


if __name__ == "__main__":
    unittest.main()
