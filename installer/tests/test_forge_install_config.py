"""Unit tests for Forge non-secret draft validation (never writes disks)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge_install_config import validate_draft

GOOD = {
    "hostname": "edos-workstation",
    "username": "developer",
    "disk_by_id": "/dev/disk/by-id/wwn-0x1234abc",
}


class ForgeDraftTests(unittest.TestCase):
    def test_valid_draft_is_not_authorization(self):
        result = validate_draft(GOOD)
        self.assertTrue(result["valid"])
        self.assertEqual(result["mode"], "dry-run-only")
        self.assertFalse(result["write_operations_enabled"])

    def test_refuses_secrets_and_executable_extra_fields(self):
        for field in ("password", "luks_passphrase", "command", "nix_options"):
            with self.subTest(field=field):
                result = validate_draft({**GOOD, field: "secret"})
                self.assertFalse(result["valid"])
                self.assertFalse(result["write_operations_enabled"])

    def test_invalid_hostname_and_username(self):
        for hostname in ("", "UPPER", "bad.", "bad-", "a"*64, "a b"):
            with self.subTest(hostname=hostname):
                self.assertFalse(validate_draft({**GOOD, "hostname": hostname})["valid"])
        for username in ("root", "nixbld", "forge", "greeter", "Upper", "hello world", "a"*32):
            with self.subTest(username=username):
                self.assertFalse(validate_draft({**GOOD, "username": username})["valid"])

    def test_refuses_unstable_or_malicious_disk_paths(self):
        for path in ("/dev/sda", "../disk", "", "/dev/disk/by-id/../../sda",
                     "/dev/disk/by-id/id;touch /tmp/foo", "/dev/disk/by-id/"):
            with self.subTest(path=path):
                self.assertFalse(validate_draft({**GOOD, "disk_by_id": path})["valid"])

    def test_invalid_payloads_do_not_crash(self):
        for payload in (None, "", [], {}, {"hostname": 3}):
            self.assertFalse(validate_draft(payload)["valid"])

    def test_accepts_supported_name_edges(self):
        self.assertTrue(validate_draft({**GOOD, "username": "_dev",
                                       "hostname": "a"})["valid"])


if __name__ == "__main__":
    unittest.main()
