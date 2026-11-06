"""Non-destructive authorization and credential fixture tests."""
import contextlib
import io
import unittest
from unittest.mock import patch

import forge_authorization as auth

ID = "/dev/disk/by-id/wwn-0xsample"
SHA = "a" * 64
REVIEW = {"snapshot": {"stable_id": ID, "eligible": True, "blockers": []},
          "sha256": SHA, "write_operations_enabled": False}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def verified(review):
    assert review == REVIEW
    return {"verified": True, "stable_id": ID,
            "sha256": SHA, "write_operations_enabled": False}


class AuthorizationTests(unittest.TestCase):
    def test_valid_user_settings(self):
        settings = auth.validate_user_settings("anaya", "eduardos")
        self.assertEqual(settings.username, "anaya")
        self.assertEqual(settings.hostname, "eduardos")

    def test_user_and_hostname_restrictions(self):
        invalid = ["root", "forge", "greeter", "nixbld", "ABC", "foo bar", "../root", "a" * 40]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(auth.Refused):
                auth.validate_user_settings(value, "eduardos")
        for value in ["LOCALHOST", "host.local", "a-" , "-host", "x" * 64]:
            with self.subTest(value=value), self.assertRaises(auth.Refused):
                auth.validate_user_settings("anaya", value)

    def test_secret_pair_length_match_and_controls(self):
        auth.validate_secret_pair("alpha beta 12345", "alpha beta 12345", kind="LUKS")
        for left, right in [("short", "short"),
                            ("longpassword123", "different123456"),
                            ("password\n123456", "password\n123456"),
                            ("password\x00123456", "password\x00123456")]:
            with self.subTest(pair=left), self.assertRaises(auth.Refused):
                auth.validate_secret_pair(left, right, kind="LUKS")

    def test_dry_run_session_requires_exact_disk_phrase(self):
        clock = Clock()
        session = auth.AuthorizationSession(REVIEW, clock=clock)
        with self.assertRaises(auth.Refused):
            session.authorize("ERASE /dev/sda", session.nonce, verify_review=verified)
        with self.assertRaisesRegex(auth.Refused, "consumed"):
            session.authorize(session.challenge, session.nonce, verify_review=verified)

    def test_one_time_success_is_not_write_authorization(self):
        clock = Clock()
        session = auth.AuthorizationSession(REVIEW, clock=clock)
        result = session.authorize(session.challenge, session.nonce, verify_review=verified)
        self.assertEqual(result["status"], "review-confirmed")
        self.assertFalse(result["write_operations_enabled"])
        self.assertNotIn("password", repr(result))
        self.assertNotIn("execute", result)
        with self.assertRaises(auth.Refused):
            session.authorize(session.challenge, session.nonce, verify_review=verified)

    def test_wrong_nonce_is_rejected_and_consumes_session(self):
        session = auth.AuthorizationSession(REVIEW, clock=Clock())
        with self.assertRaisesRegex(auth.Refused, "nonce"):
            session.authorize(session.challenge, "forged", verify_review=verified)
        with self.assertRaisesRegex(auth.Refused, "consumed"):
            session.authorize(session.challenge, session.nonce, verify_review=verified)

    def test_expired_session(self):
        clock = Clock()
        session = auth.AuthorizationSession(REVIEW, clock=clock)
        clock.now = auth.TTL_SECONDS
        with self.assertRaisesRegex(auth.Refused, "expired"):
            session.authorize(session.challenge, session.nonce, verify_review=verified)

    def test_new_disk_status_or_changed_identity_blocks(self):
        def stale(_):
            raise auth.identity.Refused("Hardware changed")
        session = auth.AuthorizationSession(REVIEW, clock=Clock())
        with self.assertRaises(auth.identity.Refused):
            session.authorize(session.challenge, session.nonce, verify_review=stale)

    def test_verifier_must_preserve_read_only(self):
        session = auth.AuthorizationSession(REVIEW, clock=Clock())
        with self.assertRaises(auth.Refused):
            session.authorize(session.challenge, session.nonce,
                              verify_review=lambda _: {"verified": True,
                                                       "write_operations_enabled": True})

    def test_credentials_require_local_tty_and_are_not_echoed(self):
        values = iter(["superlonglukspass1", "superlonglukspass1",
                       "strongaccountpass2", "strongaccountpass2"])
        settings = auth.validate_user_settings("anaya", "eduardos")
        with patch.object(auth.sys.stdin, "isatty", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            result = auth.prompt_credentials(settings, prompt=lambda _: next(values))
        self.assertIsNone(result)
        self.assertNotIn("superlong", out.getvalue())
        with patch.object(auth.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(auth.Refused):
                auth.prompt_credentials(settings, prompt=lambda _: "secret")

    def test_no_disk_api_in_authorization(self):
        # A fixture test ensures the consent module cannot invoke install,
        # Disko or root helper via its public API.
        self.assertFalse(hasattr(auth.AuthorizationSession, "install"))
        self.assertFalse(hasattr(auth.AuthorizationSession, "execute"))


if __name__ == "__main__":
    unittest.main()
