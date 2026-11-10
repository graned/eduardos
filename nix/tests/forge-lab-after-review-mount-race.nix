{ pkgs }:
# Real disposable QEMU: after a clean audit, mount /dev/vda, repeat the
# irreversible boundary audit and prove it refuses before any Disko call.
let
  raceScript = pkgs.writeText "edos-after-review-mount-race.py" ''
    import pathlib
    import subprocess
    import sys

    sys.path.insert(0, "${../../installer}")
    import forge_executor_lab as forge

    mountpoint = pathlib.Path("/run/edos-after-review-mounted")
    mountpoint.mkdir(parents=True, exist_ok=True)
    with forge.hold_lab_disk() as (fd, devno):
        forge.audit_irreversible_boundary(fd, devno)
        print("EDOS_BOUNDARY_INITIAL_REVIEW_OK", flush=True)
        subprocess.run(["mount", "/dev/vda", str(mountpoint)], check=True)
        (mountpoint / "preserve-me").write_text("safe")
        try:
            forge.audit_irreversible_boundary(fd, devno)
        except (forge.Refused, forge.command_policy.Refused,
                forge.topology_guard.Refused):
            print("EDOS_BOUNDARY_AFTER_REVIEW_REFUSED", flush=True)
        else:
            raise AssertionError("Mount race was incorrectly accepted")
    assert (mountpoint / "preserve-me").read_text() == "safe"
    print("EDOS_BOUNDARY_SENTINEL_PRESERVED", flush=True)
  '';
in
pkgs.testers.runNixOSTest {
  name = "eduardos-qemu-after-review-mounted-target";
  meta.timeout = 600;
  nodes.machine = { ... }: {
    networking.hostName = "edos-mount-race-lab";
    system.stateVersion = "26.05";
    virtualisation.diskImage = "./edos-after-review-test-only.qcow2";
    virtualisation.diskSize = 10 * 1024;
    virtualisation.emptyDiskImages = [ 1024 ];
    virtualisation.rootDevice = "/dev/vdb";
    boot.initrd.systemd.enable = true;
    virtualisation.fileSystems."/".autoFormat = true;
    boot.loader.grub.enable = false;
    virtualisation.memorySize = 2048;
    virtualisation.cores = 2;
    environment.systemPackages = with pkgs; [ python3 util-linux e2fsprogs ];
    system.extraDependencies = [ ../../installer raceScript ];
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_until_succeeds("test -b /dev/vda && test -b /dev/vdb")
    machine.succeed("test -L /dev/disk/by-id/virtio-root")
    machine.succeed('test "$(readlink -f /dev/disk/by-id/virtio-root)" = /dev/vda')
    machine.succeed("mkfs.ext4 -F /dev/vda")
    machine.succeed("test ! -e /run/eduardos-qemu-format-attempted")
    with subtest("After-review mount refuses while the target FD is held"):
        output = machine.succeed("${pkgs.python3}/bin/python3 ${raceScript}")
        assert "EDOS_BOUNDARY_INITIAL_REVIEW_OK" in output, output
        assert "EDOS_BOUNDARY_AFTER_REVIEW_REFUSED" in output, output
        assert "EDOS_BOUNDARY_SENTINEL_PRESERVED" in output, output
        machine.succeed("test ! -e /run/eduardos-qemu-format-attempted")
        machine.succeed('test "$(cat /run/edos-after-review-mounted/preserve-me)" = safe')
        machine.succeed(
            "findmnt -n -o SOURCE /run/edos-after-review-mounted | grep -Fx /dev/vda"
        )
        machine.succeed("umount /run/edos-after-review-mounted")
  '';
}
