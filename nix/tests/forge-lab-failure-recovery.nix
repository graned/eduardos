{ pkgs }:

# Disposable REAL block-device fault test. No host or physical disks.
# /dev/vda is a throwaway sparse qcow2 disk, /dev/vdb is the VM root.
# The fake Disko command writes a GPT to /dev/vda and exits nonzero.
# This verifies that the REAL guarded QEMU executor refuses a retry.
let
  fakeSystem = pkgs.runCommand "edos-recovery-test-closure" {} ''
    mkdir -p "$out"
  '';
  partialDisko = pkgs.writeShellScript "edos-partial-failure-disko" ''
    if [ "$#" -ne 1 ] || [ "$1" != "--yes-wipe-all-disks" ]; then
      exit 98
    fi
    # Destructive, but restricted to the disposable QEMU guest /dev/vda.
    ${pkgs.parted}/bin/parted --script /dev/vda mklabel gpt
    # Simulate failure AFTER the first irreversible metadata write.
    exit 49
  '';
  executor = "${pkgs.python3}/bin/python3 ${../../installer}/forge_executor_lab.py";
in
pkgs.testers.runNixOSTest {
  name = "eduardos-qemu-partial-format-recovery";
  meta.timeout = 900;

  nodes.machine = { ... }: {
    networking.hostName = "edos-recovery-lab";
    system.stateVersion = "26.05";
    virtualisation.diskImage = "./edos-recovery-test-only.qcow2";
    virtualisation.diskSize = 10 * 1024;
    virtualisation.emptyDiskImages = [ 1024 ];
    virtualisation.rootDevice = "/dev/vdb";
    boot.initrd.systemd.enable = true;
    virtualisation.fileSystems."/".autoFormat = true;
    boot.loader.grub.enable = false;
    virtualisation.memorySize = 2048;
    virtualisation.cores = 2;
    environment.systemPackages = with pkgs; [
      python3 util-linux parted cryptsetup
    ];
    system.extraDependencies = [ ../../installer partialDisko fakeSystem ];
  };

  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_until_succeeds("test -b /dev/vda && test -b /dev/vdb")
    machine.succeed("test -L /dev/disk/by-id/virtio-root")
    machine.succeed(
        "test \"$(readlink -f /dev/disk/by-id/virtio-root)\" = /dev/vda"
    )
    machine.succeed(
        "printf 'EDOS-LAB-ONLY' > /run/eduardos-disposable-install-lab"
    )
    machine.succeed(
        "umask 077; printf 'edos-disposable-test-passphrase' "
        "> /run/edos-test-passphrase"
    )
    machine.succeed(
        "umask 077; printf 'edos-public-recovery-test-password-44' "
        "> /run/edos-public-recovery-password"
    )
    machine.succeed("test ! -e /run/eduardos-qemu-format-attempted")
    machine.succeed("test ! -e /dev/vda1")
    command = (
        "${executor} --disko-script ${partialDisko} "
        "--system-closure ${fakeSystem} --execute "
        "--confirm 'ERASE DISPOSABLE /dev/vda' "
        "--user-password-stdin </run/edos-public-recovery-password 2>&1"
    )

    # The NixOS driver type-checker cannot resolve local dynamic imports.
    # Load the pinned source directly and assess actual captured VM output.
    import runpy
    assess_progress = runpy.run_path("${../../installer/forge_lab_progress.py}")["assess"]

    with subtest("Actual disposable disk receives partial GPT before intentional failure"):
        status, output = machine.execute(command)
        assert status != 0, "Injected partial Disko failure must fail"
        assert "FORGE_QEMU_PHASE=format-started" in output, output[-3000:]
        assert "FORGE_QEMU_PHASE=halted-after-format-started" in output, output[-3000:]
        assert "FORGE_QEMU_PHASE=formatted" not in output
        assert "FORGE_QEMU_PHASE=installed" not in output
        observed = assess_progress(output, process_returncode=status)
        assert observed["status"] == "manual-recovery-required", observed
        assert observed["complete"] is False
        assert observed["authorization_to_write"] is False
        assert observed["automatic_retry_enabled"] is False
        machine.succeed("test -f /run/eduardos-qemu-format-attempted")
        machine.succeed(
            "test \"$(stat -c %a /run/eduardos-qemu-format-attempted)\" = 600"
        )
        machine.wait_until_succeeds(
            "lsblk -dnro PTTYPE /dev/vda | grep -Fx gpt"
        )
        machine.succeed("test ! -e /dev/vda1")
        machine.succeed("test ! -e /dev/mapper/edos-crypt")
        machine.succeed(
            "test ! -e /mnt/persist/eduardos/credentials/testpilot.hash"
        )

    with subtest("Second process refused before formatter, even with identical confirmation"):
        status, output = machine.execute(command)
        assert status != 0, "Second attempt must fail"
        assert "attempt already started" in output, output[-3000:]
        assert "FORGE_QEMU_PHASE=format-started" not in output
        assert "FORGE_QEMU_PHASE=installed" not in output
        blocked = assess_progress(output, process_returncode=status)
        assert blocked["status"] == "incomplete-unknown-disk-state", blocked
        assert blocked["complete"] is False
        assert blocked["automatic_retry_enabled"] is False
        machine.succeed(
            "lsblk -dnro PTTYPE /dev/vda | grep -Fx gpt"
        )
        machine.succeed("test -f /run/eduardos-qemu-format-attempted")

    with subtest("Recovery classification exposes no retry or write authority"):
        machine.succeed(
            "${pkgs.python3}/bin/python3 -B -c "
            "'import sys;sys.path.insert(0,\"${../../installer}\");"
            "import forge_lab_attempt as a;r=a.recovery_report();"
            "assert r[\"status\"]==\"manual-recovery-required\";"
            "assert r[\"write_operations_enabled\"] is False;"
            "assert r[\"auto_retry_enabled\"] is False;"
            "assert r[\"automatic_rollback_enabled\"] is False'"
        )
        machine.succeed("rm /run/edos-public-recovery-password")
        machine.succeed("test ! -e /mnt/persist")
  '';
}
