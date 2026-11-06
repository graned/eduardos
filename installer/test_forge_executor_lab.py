"""No destructive tests: all executor calls are mocked and fail closed."""
import contextlib
import io
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
             patch.object(executor.subprocess, "run") as run:
            executor.install("/nix/store/fake/bin/disko", "/nix/store/fake-system")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0],
                             ["/nix/store/fake/bin/disko", "--yes-wipe-all-disks"])
            self.assertEqual(run.call_args_list[1].args[0][0], "nixos-install")
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
