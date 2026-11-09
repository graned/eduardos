"""PR #43: no-disk fault injection for live QEMU irreversible Disko audit.

All actual subprocess calls and block devices are mocked in these
unit tests. The separately dispatched destructive QEMU workflow tests
real Disko, LUKS, cold boot and login on a disposable qcow2 image.
"""
from __future__ import annotations

from contextlib import nullcontext, redirect_stdout
import io
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import forge_executor_lab as executor
import forge_lab_command_policy as policy


SCRIPT = "/nix/store/fake-disko/bin/disko"
SYSTEM = "/nix/store/fake-installed"


class IrreversibleBoundaryTests(unittest.TestCase):
    def setUp(self):
        # These suites mock all subprocess/disk operations. The real
        # same-boot attempt marker is tested separately in a QEMU guest.
        for name in ("require_new_attempt", "mark_format_started"):
            patcher = patch.object(executor.lab_attempt, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fresh_kernel_sources_rechecked_while_fd_is_held(self):
        disk_graph = {"blockdevices": [{"path": "/dev/vda", "type": "disk"}]}
        with patch.object(executor, "_assert_held_target") as held, \
             patch.object(executor.identity, "probe", return_value=disk_graph) as probe, \
             patch.object(executor.Path, "read_text",
                          side_effect=["mounted-root-evidence", "swap-evidence"]), \
             patch.object(executor.live_media, "sysfs_loop_backings",
                          return_value={"loop": "iso"}) as loops, \
             patch.object(executor.command_policy, "review_kernel_boundary",
                          return_value={
                              "status": "lab-boundary-reviewed-read-only",
                              "target_devno": "252:0",
                              "write_operations_enabled": False,
                              "authorization_to_write": False,
                          }) as guard:
            executor.audit_irreversible_boundary(77, "252:0")
        self.assertEqual(held.call_count, 2)
        held.assert_any_call(77, "252:0")
        probe.assert_called_once()
        loops.assert_called_once()
        guard.assert_called_once_with(
            "252:0", data=disk_graph, mountinfo="mounted-root-evidence",
            swaps="swap-evidence", loop_backings={"loop": "iso"},
        )

    def test_held_fd_replacement_aborts_without_kernel_probe(self):
        with patch.object(executor, "_assert_held_target",
                          side_effect=executor.Refused("disk changed")) as check, \
             patch.object(executor.identity, "probe") as probe, \
             patch.object(executor.command_policy, "review_kernel_boundary") as audit:
            with self.assertRaisesRegex(executor.Refused, "disk changed"):
                executor.audit_irreversible_boundary(77, "252:0")
            check.assert_called_once_with(77, "252:0")
            probe.assert_not_called()
            audit.assert_not_called()

    def test_mount_swap_boot_or_target_failure_blocks_boundary(self):
        cases = [
            {"target_devno": "252:16"},
            {"write_operations_enabled": True},
            {"authorization_to_write": True},
            {"status": "failed"},
        ]
        valid = {
            "status": "lab-boundary-reviewed-read-only",
            "target_devno": "252:0",
            "write_operations_enabled": False,
            "authorization_to_write": False,
        }
        for bad in cases:
            with self.subTest(bad=bad), \
                 patch.object(executor, "_assert_held_target") as held, \
                 patch.object(executor.identity, "probe", return_value={}), \
                 patch.object(executor.Path, "read_text", return_value="fixture"), \
                 patch.object(executor.live_media, "sysfs_loop_backings",
                              return_value={}), \
                 patch.object(executor.command_policy, "review_kernel_boundary",
                              return_value={**valid, **bad}):
                with self.assertRaisesRegex(executor.Refused, "audit refused"):
                    executor.audit_irreversible_boundary(77, "252:0")
                held.assert_called_once_with(77, "252:0")

        with patch.object(executor, "_assert_held_target") as held, \
             patch.object(executor.identity, "probe", return_value={}), \
             patch.object(executor.Path, "read_text", return_value="fixture"), \
             patch.object(executor.live_media, "sysfs_loop_backings", return_value={}), \
             patch.object(executor.command_policy, "review_kernel_boundary",
                          side_effect=policy.Refused("active protected swap")):
            with self.assertRaisesRegex(policy.Refused, "protected swap"):
                executor.audit_irreversible_boundary(77, "252:0")
            held.assert_called_once_with(77, "252:0")

    def test_disk_alias_replaced_after_kernel_proof_refuses(self):
        with patch.object(executor, "_assert_held_target",
                          side_effect=[None, executor.Refused("path switched")]) as held, \
             patch.object(executor.identity, "probe", return_value={}), \
             patch.object(executor.Path, "read_text", return_value="fixture"), \
             patch.object(executor.live_media, "sysfs_loop_backings", return_value={}), \
             patch.object(executor.command_policy, "review_kernel_boundary",
                          return_value={
                              "status": "lab-boundary-reviewed-read-only",
                              "target_devno": "252:0",
                              "write_operations_enabled": False,
                              "authorization_to_write": False,
                          }):
            with self.assertRaisesRegex(executor.Refused, "path switched"):
                executor.audit_irreversible_boundary(77, "252:0")
            self.assertEqual(held.call_count, 2)

    def run_guarded_lab(self, *, review=None, kernel_failure=None,
                        process_failure=None):
        reviewed = review
        if reviewed is None:
            reviewed = SimpleNamespace(
                disk="/dev/vda", write_operations_enabled=False,
                authorization_to_write=False,
                format_step=SimpleNamespace(
                    executable=False, arguments=(SCRIPT, "--yes-wipe-all-disks"),
                ),
                install_step=SimpleNamespace(
                    executable=False,
                    arguments=("nixos-install", "--root", "/mnt", "--system",
                               SYSTEM, "--no-root-passwd"),
                ),
            )
        output = io.StringIO()
        with patch.object(executor.Path, "is_file", return_value=True), \
             patch.object(executor.Path, "is_dir", return_value=True), \
             patch.object(executor, "check_lab_guard", return_value=[]), \
             patch.object(executor.command_policy, "review_commands",
                          return_value=reviewed), \
             patch.object(executor, "hold_lab_disk",
                          return_value=nullcontext((77, "252:0"))) as holder, \
             patch.object(executor, "_assert_held_target"), \
             patch.object(executor, "audit_irreversible_boundary",
                          side_effect=kernel_failure) as kernel, \
             patch.object(executor, "verify_post_format"), \
             patch.object(executor, "stage_lab_account"), \
             patch.object(executor.lab_child, "run_child",
                          side_effect=process_failure) as subprocess_run, \
             redirect_stdout(output):
            if review is None or reviewed.disk == "/dev/vda":
                with self.assertRaises((executor.Refused,
                                        subprocess.CalledProcessError)):
                    executor.install(
                        SCRIPT, SYSTEM,
                        password_stream=io.BytesIO(b"disposable-fixture-password-1234"),
                    )
            else:
                with self.assertRaisesRegex(executor.Refused, "allowlist"):
                    executor.install(
                        SCRIPT, SYSTEM,
                        password_stream=io.BytesIO(b"disposable-fixture-password-1234"),
                    )
        return output.getvalue(), holder, kernel, subprocess_run

    def test_disk_guard_failure_after_format_started_runs_no_formatter(self):
        text, _, kernel, process = self.run_guarded_lab(
            kernel_failure=executor.Refused("new active mount detected"),
        )
        kernel.assert_called_once_with(77, "252:0")
        process.assert_not_called()
        self.assertIn("FORGE_QEMU_PHASE=format-started", text)
        self.assertIn("FORGE_QEMU_PHASE=halted-after-format-started", text)
        self.assertNotIn("FORGE_QEMU_PHASE=formatted", text)

    def test_failed_formatter_is_never_retried_and_install_never_starts(self):
        text, _, kernel, process = self.run_guarded_lab(
            process_failure=subprocess.CalledProcessError(1, [SCRIPT]),
        )
        kernel.assert_called_once_with(77, "252:0")
        process.assert_called_once()
        self.assertEqual(
            process.call_args.args[0],
            [SCRIPT, "--yes-wipe-all-disks"],
        )
        self.assertIn("FORGE_QEMU_PHASE=halted-after-format-started", text)
        self.assertNotIn("FORGE_QEMU_PHASE=installed", text)

    def test_altered_command_contract_cannot_reach_block_device(self):
        reviewed = SimpleNamespace(
            disk="/dev/sda", write_operations_enabled=False,
            authorization_to_write=False,
            format_step=SimpleNamespace(
                executable=False, arguments=(SCRIPT, "--yes-wipe-all-disks"),
            ),
            install_step=SimpleNamespace(
                executable=False,
                arguments=("nixos-install", "--root", "/mnt", "--system",
                           SYSTEM, "--no-root-passwd"),
            ),
        )
        _, holder, kernel, process = self.run_guarded_lab(review=reviewed)
        holder.assert_not_called()
        kernel.assert_not_called()
        process.assert_not_called()

    def test_physical_target_and_gui_remain_disconnected(self):
        self.assertEqual(executor.TARGET, "/dev/vda")
        self.assertEqual(executor.CONFIRM, "ERASE DISPOSABLE /dev/vda")
        self.assertFalse(hasattr(policy, "format_disk"))
        self.assertFalse(hasattr(policy, "install"))
        self.assertFalse(hasattr(policy, "execute"))
        self.assertFalse(hasattr(policy, "subprocess"))


if __name__ == "__main__":
    unittest.main()
