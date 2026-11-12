"""Fail-closed tests for the explicit VM-only ISO installation entrypoint.

No marker is created on the test host, no root process, no real disk writes.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_vm_iso_launcher as launcher


class VmIsoLauncherTests(unittest.TestCase):
    def test_non_root_rejected_before_marker_or_gui(self):
        with mock.patch.object(launcher.os, "geteuid", return_value=1000), \
             mock.patch.object(launcher.executor, "MARKER") as marker, \
             mock.patch.object(launcher.gui, "main") as gui:
            self.assertEqual(launcher.main(["--executor", "/nix/store/fake"]), 2)
            marker.assert_not_called()
            gui.assert_not_called()

    def test_non_interactive_root_rejected_without_prompt(self):
        with mock.patch.object(launcher.os, "geteuid", return_value=0), \
             mock.patch.object(launcher.sys.stdin, "isatty", return_value=False), \
             mock.patch.object(launcher.gui, "main") as gui:
            self.assertEqual(launcher.main(["--executor", "/nix/store/fake"]), 2)
            gui.assert_not_called()

    def test_non_qemu_dmi_rejected_before_marker(self):
        def fake_dmi(self, *args, **kwargs):
            return "Acme Physical Laptop"
        with mock.patch.object(launcher.os, "geteuid", return_value=0), \
             mock.patch.object(launcher.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(Path, "read_text", fake_dmi), \
             mock.patch.object(launcher.os, "open") as open_file, \
             mock.patch.object(launcher.gui, "main") as gui:
            self.assertEqual(launcher.main(["--executor", "/nix/store/fake"]), 2)
            open_file.assert_not_called()
            gui.assert_not_called()

    def test_qemu_with_wrong_stable_disk_refused(self):
        with mock.patch.object(launcher.os, "geteuid", return_value=0), \
             mock.patch.object(launcher.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(Path, "read_text", return_value="QEMU"), \
             mock.patch.object(Path, "is_symlink", return_value=False), \
             mock.patch.object(launcher.os, "open") as open_file:
            self.assertEqual(launcher.main(["--executor", "/nix/store/fake"]), 2)
            open_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
