"""Pure tests of the physical installation plan: never opens devices."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge_physical_command_policy import (
    PHASES, Refused, review_fixed_plan, verify_no_write_authority,
)

GOOD = {
    "target_id": "/dev/disk/by-id/wwn-0x123",
    "target_devno": "8:0",
    "disko_script": "/nix/store/" + "a" * 32 + "-disko/bin/disko",
    "system_closure": "/nix/store/" + "b" * 32 + "-nixos-system",
}


class FixedPlanTests(unittest.TestCase):
    def test_all_steps_are_non_executable_and_ordered(self):
        review = review_fixed_plan(**GOOD)
        self.assertEqual(tuple(x.phase for x in review.phases), PHASES)
        self.assertFalse(review.write_operations_enabled)
        self.assertFalse(review.authorization_to_write)
        self.assertFalse(review.executable)
        self.assertTrue(all(not x.executable for x in review.phases))
        verify_no_write_authority(review)

    def test_arbitrary_devices_and_commands_are_not_allowed(self):
        overrides = (
            ("target_id", "/dev/sda"),
            ("target_id", "/dev/disk/by-id/../sda"),
            ("target_id", "/dev/disk/by-id/id;sh"),
            ("target_devno", "../8:0"),
            ("disko_script", "/bin/sh"),
            ("disko_script", GOOD["disko_script"] + "/../evil"),
            ("system_closure", "/nix/store/" + "b" * 32 + "-nixos-system;rm"),
        )
        for key, value in overrides:
            with self.subTest(key=key, value=value):
                with self.assertRaises(Refused):
                    review_fixed_plan(**{**GOOD, key: value})

    def test_no_authorization_can_be_injected(self):
        review = review_fixed_plan(**GOOD)
        for field in ("write_operations_enabled", "authorization_to_write", "executable"):
            with self.subTest(field=field), self.assertRaises(Refused):
                verify_no_write_authority(replace(review, **{field: True}))

    def test_no_extra_writable_arguments_supported(self):
        with self.assertRaises(TypeError):
            review_fixed_plan(**GOOD, arbitrary_command=["sh", "-c", "erase"])
        with self.assertRaises(TypeError):
            review_fixed_plan(**GOOD, secret="never")
        with self.assertRaises(TypeError):
            review_fixed_plan(**GOOD, run=True)


if __name__ == "__main__":
    unittest.main()
