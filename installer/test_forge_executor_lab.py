"""No destructive tests: all executor calls are mocked and fail closed."""
import contextlib
import io
import os
import unittest
from unittest.mock import patch, MagicMock

import forge_executor_lab as executor


class LabExecutorTests(unittest.TestCase):
    def args(self, *extra):
        return ["--disko-script", "/nix/store/fake-disko/bin/disko",
                "--system-closure", "/nix/store/fake-system", *extra]

    def test_default_dry_run_never_checks_or_runs_install(self):
        with patch.object(executor, "check_lab_guard") as guard, \
             patch.object(executor, "install") as install, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(executor.main(self.args()), 0)
            guard.assert_not_called()
            install.assert_not_called()

    def test_execution_requires_exact_confirmation(self):
        with patch.object(executor, "check_lab_guard") as guard, \
             patch.object(executor, "install") as install, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(executor.main(self.args("--execute")), 2)
            self.assertEqual(executor.main(self.args("--execute", "--confirm", "yes")), 2)
            guard.assert_not_called()
            install.assert_not_called()

    def test_refuses_when_any_guard_fails(self):
        with patch.object(executor, "check_lab_guard", return_value=["not QEMU"]), \
             patch.object(executor, "install") as install, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(executor.main(self.args("--execute", "--confirm", executor.CONFIRM)), 2)
            install.assert_not_called()

    def test_guard_must_be_exact_vda_target(self):
        self.assertEqual(executor.TARGET, "/dev/vda")
        self.assertEqual(executor.CONFIRM, "ERASE DISPOSABLE /dev/vda")

    def test_executor_uses_argument_arrays_not_shell(self):
        with patch.object(executor.Path, "is_file", return_value=True), \
             patch.object(executor.Path, "is_dir", return_value=True), \
             patch.object(executor, "check_lab_guard", return_value=[]), \
             patch.object(executor, "hold_lab_disk",
                          return_value=contextlib.nullcontext((42, "8:0"))), \
             patch.object(executor, "verify_post_format") as audit, \
             patch.object(executor.subprocess, "run") as run:
            executor.install("/nix/store/fake/bin/disko", "/nix/store/fake-system")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0],
                             ["/nix/store/fake/bin/disko", "--yes-wipe-all-disks"])
            self.assertEqual(run.call_args_list[1].args[0][0], "nixos-install")
            audit.assert_called_once_with(42, "8:0")
            self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))

    def test_refuses_nonstore_executables(self):
        with self.assertRaises(executor.Refused):
            executor.install("/tmp/untrusted", "/nix/store/fake-system")

    def test_write_path_only_after_all_gates(self):
        with patch.object(executor, "check_lab_guard", return_value=[]), \
             patch.object(executor, "install") as install, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(executor.main(self.args("--execute", "--confirm", executor.CONFIRM)), 0)
            install.assert_called_once()

    def test_direct_install_cannot_skip_vm_guard(self):
        with patch.object(executor.Path, "is_file", return_value=True), \
             patch.object(executor.Path, "is_dir", return_value=True), \
             patch.object(executor, "check_lab_guard",
                          return_value=["missing disposable marker"]), \
             patch.object(executor, "hold_lab_disk") as hold, \
             patch.object(executor.subprocess, "run") as run:
            with self.assertRaisesRegex(executor.Refused, "safety"):
                executor.install("/nix/store/fake/bin/disko", "/nix/store/fake-system")
            hold.assert_not_called()
            run.assert_not_called()

    def test_pre_format_ancestry_failure_aborts_before_disko(self):
        with patch.object(executor.Path, "is_file", return_value=True), \
             patch.object(executor.Path, "is_dir", return_value=True), \
             patch.object(executor, "check_lab_guard", return_value=[]), \
             patch.object(executor, "hold_lab_disk",
                          side_effect=executor.Refused("running disk")), \
             patch.object(executor.subprocess, "run") as run:
            with self.assertRaisesRegex(executor.Refused, "running disk"):
                executor.install("/nix/store/fake/bin/disko", "/nix/store/fake-system")
            run.assert_not_called()

    def test_post_format_mount_failure_blocks_nixos_install(self):
        with patch.object(executor.Path, "is_file", return_value=True), \
             patch.object(executor.Path, "is_dir", return_value=True), \
             patch.object(executor, "check_lab_guard", return_value=[]), \
             patch.object(executor, "hold_lab_disk",
                          return_value=contextlib.nullcontext((42, "8:0"))), \
             patch.object(executor, "verify_post_format",
                          side_effect=executor.Refused("wrong mounted disk")), \
             patch.object(executor.subprocess, "run") as run:
            with self.assertRaisesRegex(executor.Refused, "mounted disk"):
                executor.install("/nix/store/fake/bin/disko", "/nix/store/fake-system")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][-1], "--yes-wipe-all-disks")

    def test_postformat_audit_requires_exact_target_and_read_only_evidence(self):
        good = {
            "status": "verified-already-mounted-encrypted-target",
            "target_devno": "8:0",
            "mountpoints": executor._EXPECTED_MOUNTS,
            "destructive_disk_operations_enabled": False,
            "credential_writes_enabled": False,
        }
        with patch.object(executor, "_assert_held_target") as check, \
             patch.object(executor.mount_audit, "audit", return_value=good) as audit:
            executor.verify_post_format(42, "8:0")
            audit.assert_called_once_with("/dev/vda")
            self.assertEqual(check.call_count, 2)
        changes = [
            ("status", "unverified"),
            ("target_devno", "8:16"),
            ("mountpoints", ["/mnt"]),
            ("destructive_disk_operations_enabled", True),
            ("credential_writes_enabled", True),
        ]
        for key, invalid in changes:
            with self.subTest(key=key):
                forged = {**good, key: invalid}
                with patch.object(executor, "_assert_held_target"), \
                     patch.object(executor.mount_audit, "audit",
                                  return_value=forged):
                    with self.assertRaisesRegex(executor.Refused, "audit failed"):
                        executor.verify_post_format(42, "8:0")

    def test_hold_lab_disk_only_opens_read_only_and_closes_on_failure(self):
        safe = {"target_devno": "8:0", "write_operations_enabled": False}
        with patch.object(executor.identity, "probe", return_value={"blockdevices": []}), \
             patch.object(executor.topology_guard, "guard_topology",
                          return_value=safe) as guard, \
             patch.object(executor.live_media, "sysfs_loop_backings",
                          return_value={}), \
             patch.object(executor.Path, "read_text",
                          return_value="fixture-mounts"), \
             patch.object(executor.os, "open", return_value=42) as openfd, \
             patch.object(executor.os, "close") as closefd, \
             patch.object(executor, "_assert_held_target") as check:
            with self.assertRaisesRegex(RuntimeError, "consumer failed"):
                with executor.hold_lab_disk() as (fd, devno):
                    self.assertEqual((fd, devno), (42, "8:0"))
                    raise RuntimeError("consumer failed")
            guard.assert_called_once()
            check.assert_called_once_with(42, "8:0")
            openfd.assert_called_once_with(executor.TARGET, executor._BLOCK_READ_FLAGS)
            self.assertEqual(executor._BLOCK_READ_FLAGS & os.O_ACCMODE, os.O_RDONLY)
            closefd.assert_called_once_with(42)

    def test_block_handle_rejects_wrong_kernel_identity(self):
        with patch.object(executor.os, "fstat", return_value=type("S", (), {
            "st_mode": 0o060600, "st_rdev": os.makedev(8, 16)
        })()):
            with self.assertRaisesRegex(executor.Refused, "identity"):
                executor._assert_held_target(42, "8:0")

    def test_dmi_guard_detects_nonvirtualized_machines(self):
        with patch.object(executor.os, "geteuid", return_value=1000), \
             patch.object(executor.Path, "is_file", return_value=False), \
             patch.object(executor.Path, "read_text", return_value="Physical Vendor"), \
             patch.object(executor.Path, "exists", return_value=False):
            failures = executor.check_lab_guard()
        self.assertTrue(any("root" in error for error in failures))
        self.assertTrue(any("VM-only marker" in error for error in failures))
        self.assertTrue(any("QEMU" in error for error in failures))


if __name__ == "__main__":
    unittest.main()
