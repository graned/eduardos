"""Non-destructive lab execution contract tests.

Only inspect existing QEMU runner source, Nix store path spelling and
read-only kernel ancestry reports. Never invoke a formatter or install.
"""
from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import patch

import forge_executor_lab as executor
import forge_lab_command_policy as policy
import forge_privileged_guard as guard


SCRIPT = "/nix/store/abc1234567-edos-disko/bin/disko"
SYSTEM = "/nix/store/xyz1234567-edos-target"


class CommandPolicyTests(unittest.TestCase):
    def review(self):
        with patch.object(policy.Path, "is_file", return_value=True), \
             patch.object(policy.Path, "is_dir", return_value=True):
            return policy.review_commands(SCRIPT, SYSTEM)

    def test_two_exact_fixed_nonexecutable_commands(self):
        r = self.review()
        self.assertEqual(r.disk, "/dev/vda")
        self.assertEqual(r.format_step.phase, policy.FORMAT_PHASE)
        self.assertEqual(r.format_step.arguments,
                         (SCRIPT, "--yes-wipe-all-disks"))
        self.assertEqual(r.install_step.phase, policy.INSTALL_PHASE)
        self.assertEqual(r.install_step.arguments, (
            "nixos-install", "--root", "/mnt", "--system",
            SYSTEM, "--no-root-passwd",
        ))
        for stage in (r.format_step, r.install_step):
            self.assertIs(stage.executable, False)
        self.assertIs(r.authorization_to_write, False)
        self.assertIs(r.write_operations_enabled, False)
        self.assertEqual(r.disk, executor.TARGET)

    def test_denies_paths_outside_store_or_argv_injection(self):
        bad = [
            "/tmp/disko", "/dev/sda", "/nix/store/../tmp/disko",
            "/nix/store/abc/../../tmp/disko",
            "/nix/store/abc//disko", "/nix/store/abc/disko;",
            "/nix/store/abc/disko $(touch /tmp/x)",
            "/nix/store/abc/disko\nhello", "/nix/store/abc/",
            "/nix/store/abc/./disko", "", None, 42,
        ]
        with patch.object(policy.Path, "is_file", return_value=True), \
             patch.object(policy.Path, "is_dir", return_value=True):
            for path in bad:
                with self.subTest(path=path):
                    with self.assertRaises(policy.Refused):
                        policy.review_commands(path, SYSTEM)
                    with self.assertRaises(policy.Refused):
                        policy.review_commands(SCRIPT, path)

    def test_symlink_outside_store_is_denied(self):
        with patch.object(policy.Path, "is_file", return_value=True), \
             patch.object(policy.Path, "is_dir", return_value=True), \
             patch.object(policy.os.path, "realpath",
                          return_value="/tmp/writable-disko"):
            with self.assertRaisesRegex(policy.Refused, "outside"):
                policy.review_commands(SCRIPT, SYSTEM)

    def test_missing_store_files_are_refused(self):
        with patch.object(policy.Path, "is_file", return_value=False), \
             patch.object(policy.Path, "is_dir", return_value=True):
            with self.assertRaisesRegex(policy.Refused, "regular file"):
                policy.review_commands(SCRIPT, SYSTEM)
        with patch.object(policy.Path, "is_file", return_value=True), \
             patch.object(policy.Path, "is_dir", return_value=False):
            with self.assertRaisesRegex(policy.Refused, "directory"):
                policy.review_commands(SCRIPT, SYSTEM)

    def test_live_qemu_runner_uses_exact_reviewed_argv(self):
        # Safety tripwire: any future change to the actual QEMU runner's
        # supervised child argv fails this build until the execution contract
        # and its threat-model documentation are separately reviewed.
        tree = ast.parse(inspect.getsource(executor.install))
        def runs(func_name):
            nested = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == func_name
            ]
            self.assertEqual(len(nested), 1)
            calls = [
                node for node in ast.walk(nested[0])
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "lab_child"
                and node.func.attr == "run_child"
            ]
            self.assertEqual(len(calls), 1)
            self.assertTrue(isinstance(calls[0].args[0], ast.List))
            values = []
            named = {"disko_script": SCRIPT, "system_closure": SYSTEM}
            for node in calls[0].args[0].elts:
                if isinstance(node, ast.Name) and node.id in named:
                    values.append(named[node.id])
                else:
                    values.append(ast.literal_eval(node))
            self.assertEqual(calls[0].keywords, [])
            return tuple(values)
        review = self.review()
        self.assertEqual(runs("format_disposable"), review.format_step.arguments)
        self.assertEqual(runs("install_disposable"), review.install_step.arguments)
        self.assertIn("check_lab_guard()", inspect.getsource(executor.install))
        self.assertIn("_assert_held_target(fd, devno)",
                      inspect.getsource(executor.install))
        self.assertEqual(executor.CONFIRM, "ERASE DISPOSABLE /dev/vda")

    def test_readonly_mount_and_swap_audit_is_bound_to_held_devno(self):
        proof = {
            "target_path": "/dev/vda",
            "target_devno": "252:0",
            "write_operations_enabled": False,
        }
        with patch.object(policy.topology_guard, "guard_topology",
                          return_value=proof) as check:
            result = policy.review_kernel_boundary(
                "252:0", data={"blockdevices": []},
                mountinfo="kernel-fixture", swaps="none", loop_backings={},
            )
        self.assertEqual(result["status"],
                         "lab-boundary-reviewed-read-only")
        self.assertIs(result["authorization_to_write"], False)
        check.assert_called_once_with(
            "/dev/vda", {"blockdevices": []}, "kernel-fixture", "none",
            loop_backings={},
        )

    def test_refuses_live_media_swap_or_disk_identity_changes(self):
        valid = {
            "target_path": "/dev/vda", "target_devno": "252:0",
            "write_operations_enabled": False,
        }
        for changed in (
            {**valid, "target_devno": "252:16"},
            {**valid, "target_path": "/dev/nvme0n1"},
            {**valid, "write_operations_enabled": True},
            {**valid, "status": "write-authorized"},
        ):
            with self.subTest(report=changed):
                # The extra status field is not trusted, but it must
                # never elevate the returned read-only capability.
                with patch.object(policy.topology_guard, "guard_topology",
                                  return_value=changed):
                    if (changed["target_path"] == "/dev/vda"
                            and changed["target_devno"] == "252:0"
                            and changed["write_operations_enabled"] is False):
                        report = policy.review_kernel_boundary(
                            "252:0", data={}, mountinfo="", swaps="",
                            loop_backings={},
                        )
                        self.assertIs(report["authorization_to_write"], False)
                    else:
                        with self.assertRaises(policy.Refused):
                            policy.review_kernel_boundary(
                                "252:0", data={}, mountinfo="", swaps="",
                                loop_backings={},
                            )
        with patch.object(policy.topology_guard, "guard_topology",
                          side_effect=guard.Refused("active swap backs disk")):
            with self.assertRaisesRegex(policy.Refused, "audit refused"):
                policy.review_kernel_boundary(
                    "252:0", data={}, mountinfo="", swaps="",
                    loop_backings={},
                )

    def test_refuses_malformed_kernel_evidence_before_guard(self):
        for devno, mounts, swaps, backs in (
            ("not-a-devno", "", "", {}),
            ("252:0", None, "", {}),
            ("252:0", "", None, {}),
            ("252:0", "", "", None),
        ):
            with self.subTest(devno=devno, mounts=mounts), \
                 patch.object(policy.topology_guard, "guard_topology") as check:
                with self.assertRaisesRegex(policy.Refused, "evidence"):
                    policy.review_kernel_boundary(
                        devno, data={}, mountinfo=mounts,
                        swaps=swaps, loop_backings=backs,
                    )
                check.assert_not_called()

    def test_contract_has_no_destructive_execution_api(self):
        for name in ("subprocess", "run", "execute", "install",
                     "format_disk", "mount", "shell", "authorize_disk",
                     "grant_root", "main"):
            self.assertFalse(hasattr(policy, name))
        self.assertFalse(
            any("subprocess.run" in inspect.getsource(obj)
                for obj in (policy.review_commands,
                            policy.review_kernel_boundary))
        )


if __name__ == "__main__":
    unittest.main()
