{ pkgs }:

# Destructive test SETUP is restricted to a disposable QEMU /dev/vda.
# The guarded Forge executor must refuse the already-mounted candidate
# before its own format attempt marker or any Disko child process.
let
  fakeSystem = pkgs.runCommand "edos-mount-race-test-closure" {} ''
    mkdir -p "$out"
  '';
  # Sentinel test command: if invoked, it would record an unexpected
  # formatter launch; it never receives execution authorization here.
  forbiddenDisko = pkgs.writeShellScript "edos-mount-refusal-disko" ''
    touch /run/edos-unexpected-disko-invocation
    exit 99
  '';
  executor = "${pkgs.python3}/bin/python3 ${../../installer}/forge_executor_lab.py";
in
pkgs.testers.runNixOSTest {
  name = "eduardos-qemu-mounted-target-refusal";
  meta.timeout = 600;

  nodes.machine = { ... }: {
    networking.hostName = "edos-mount-refusal-lab";
    system.stateVersion = "26.05";
    virtualisation.diskImage = "./edos-mount-refusal-test-only.qcow2";
    virtualisation.diskSize = 10 * 1024;
    virtualisation.emptyDiskImages = [ 1024 ];
    virtualisation.rootDevice = "/dev/vdb";
    boot.initrd.systemd.enable = true;
    virtualisation.fileSystems."/".autoFormat = true;
    boot.loader.grub.enable = false;
    virtualisation.memorySize = 2048;
    virtualisation.cores = 2;
    environment.systemPackages = with pkgs; [
      python3 util-linux e2fsprogs
    ];
    system.extraDependencies = [ ../../installer forbiddenDisko fakeSystem ];
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
        "umask 077; printf 'edos-public-mount-test-password-49' "
        "> /run/edos-mount-test-password"
    )

    with subtest("Mount the exact candidate device in an isolated QEMU guest"):
        # mkfs touches only the throwaway /dev/vda, never host storage.
        machine.succeed("mkfs.ext4 -F /dev/vda")
        machine.succeed("mkdir -p /run/edos-mounted-candidate")
        machine.succeed("mount /dev/vda /run/edos-mounted-candidate")
        machine.succeed(
            "printf 'preserve-me' > /run/edos-mounted-candidate/sentinel"
        )
        machine.succeed("sync")
        machine.succeed(
            "findmnt -n -o SOURCE /run/edos-mounted-candidate | grep -Fx /dev/vda"
        )
        machine.succeed("test ! -e /run/eduardos-qemu-format-attempted")
        machine.succeed("test ! -e /run/edos-unexpected-disko-invocation")

    with subtest("Forge refuses mounted target before calling formatter"):
        command = (
            "${executor} --disko-script ${forbiddenDisko} "
            "--system-closure ${fakeSystem} --execute "
            "--confirm 'ERASE DISPOSABLE /dev/vda' "
            "--user-password-stdin </run/edos-mount-test-password 2>&1"
        )
        status, output = machine.execute(command)
        assert status != 0, "Mounted target must be rejected"
        assert "FORGE_QEMU_PHASE=format-started" not in output, output[-3000:]
        assert "FORGE_QEMU_PHASE=formatted" not in output, output[-3000:]
        assert "FORGE_QEMU_PHASE=installed" not in output, output[-3000:]
        machine.succeed("test ! -e /run/eduardos-qemu-format-attempted")
        machine.succeed("test ! -e /run/edos-unexpected-disko-invocation")
        machine.succeed(
            "test \"$(cat /run/edos-mounted-candidate/sentinel)\" = preserve-me"
        )
        machine.succeed(
            "findmnt -n -o SOURCE /run/edos-mounted-candidate | grep -Fx /dev/vda"
        )
        machine.succeed("umount /run/edos-mounted-candidate")
        machine.succeed("rm -f /run/edos-mount-test-password")
  '';
}
