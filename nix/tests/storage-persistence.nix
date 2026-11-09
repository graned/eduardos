{ pkgs, modules, provisioner, mountAuditor }:

pkgs.testers.runNixOSTest {
  name = "eduardos-encrypted-storage";
  nodes.machine = { ... }: {
    imports = modules;
    networking.hostName = "eduardos-storage-test";
    system.stateVersion = "26.05";

    # Separate, disposable QEMU disk. The existing boot/root VM stays intact.
    virtualisation.emptyDiskImages = [ 4096 ];
    virtualisation.memorySize = 2048;
    environment.systemPackages = [ provisioner mountAuditor pkgs.cryptsetup pkgs.btrfs-progs pkgs.util-linux ];
  };

  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_until_succeeds("test -b /dev/vdb", timeout=40)
    machine.succeed("lsblk -f")

    # A destructive command must require both an explicit acknowledgment
    # and an actual caller-provided key file.
    machine.fail("edos-storage-provision --destroy-disposable-disk /dev/vdb")
    machine.fail("edos-storage-provision /dev/vdb")
    machine.succeed("test ! -e /dev/vdb1")

    machine.succeed(
      "umask 077; printf 'disposable-QEMU-only-storage-test-key\n' "
      "> /run/edos-storage-test.key"
    )
    machine.succeed(
      "EDOS_LUKS_KEYFILE=/run/edos-storage-test.key "
      "edos-storage-provision --destroy-disposable-disk /dev/vdb"
    )
    machine.succeed("blkid /dev/vdb1 | grep -Fq 'TYPE=\"vfat\"'")
    machine.succeed("cryptsetup isLuks --type luks2 /dev/vdb2")

    # Reopen and validate every subvolume. Ensure the provisioner didn't
    # leave active mounts or a mapped device behind.
    machine.fail("test -e /dev/mapper/edos-crypt")
    machine.succeed(
      "cryptsetup open --key-file /run/edos-storage-test.key "
      "/dev/vdb2 edos-crypt"
    )
    machine.succeed("mkdir -p /mnt/edos-volume")
    for name in ["root", "home", "nix", "persist", "snapshots"]:
        machine.succeed(
          f"mount -o subvol=@{name},compress=zstd,noatime "
          f"/dev/mapper/edos-crypt /mnt/edos-volume"
        )
        machine.succeed(
          f"printf 'retained-{name}' > /mnt/edos-volume/edos-marker"
        )
        machine.succeed("umount /mnt/edos-volume")
    # PR #30: verify our backend against REAL mountinfo, lsblk ancestry and
    # the kernel's actual Btrfs subvolume mount roots, not fixture strings.
    # Only this disposable /dev/vdb is formatted by the existing VM test.
    with subtest("Attest real mounted encrypted target and reject missing mounts"):
        machine.succeed(
          "mount -o subvol=@root,compress=zstd,noatime "
          "/dev/mapper/edos-crypt /mnt"
        )
        for name, point in [
            ("home", "home"),
            ("nix", "nix"),
            ("persist", "persist"),
            ("snapshots", ".snapshots"),
        ]:
            machine.succeed(f"mkdir -p /mnt/{point}")
            machine.succeed(
              f"mount -o subvol=@{name},compress=zstd,noatime "
              f"/dev/mapper/edos-crypt /mnt/{point}"
            )
        machine.succeed("mkdir -p /mnt/boot")
        machine.succeed("mount /dev/vdb1 /mnt/boot")
        machine.succeed("forge-mount-audit --disk /dev/vdb > /run/edos-mounted-audit.json")
        machine.succeed("grep -Fq 'verified-already-mounted-encrypted-target' /run/edos-mounted-audit.json")
        machine.succeed("grep -Fq 'destructive_disk_operations_enabled' /run/edos-mounted-audit.json")
        # A parent boot disk must never pass as the selected target.
        machine.fail("forge-mount-audit --disk /dev/vda")
        # Unmount one encrypted subvolume: audit must immediately fail.
        machine.succeed("umount /mnt/persist")
        machine.fail("forge-mount-audit --disk /dev/vdb")
        machine.succeed(
          "mount -o subvol=@persist,compress=zstd,noatime "
          "/dev/mapper/edos-crypt /mnt/persist"
        )
        machine.succeed("forge-mount-audit --disk /dev/vdb")
        machine.succeed("umount -R /mnt")
        machine.fail("forge-mount-audit --disk /dev/vdb")

    machine.succeed("cryptsetup close edos-crypt")

    # Shut down the guest cleanly, then cold-boot the SAME QEMU disk image.
    # This Nix test harness disconnects its control shell on guest reboot.
    # A fresh start checks disk persistence more strictly than remount alone.
    machine.shutdown()
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.succeed(
      "umask 077; printf 'disposable-QEMU-only-storage-test-key\n' "
      "> /run/edos-storage-test.key"
    )
    machine.succeed(
      "cryptsetup open --key-file /run/edos-storage-test.key "
      "/dev/vdb2 edos-crypt"
    )
    machine.succeed("mkdir -p /mnt/edos-volume")
    for name in ["root", "home", "nix", "persist", "snapshots"]:
        machine.succeed(
          f"mount -o subvol=@{name},compress=zstd,noatime "
          f"/dev/mapper/edos-crypt /mnt/edos-volume"
        )
        machine.succeed(
          f"grep -Fxq retained-{name} /mnt/edos-volume/edos-marker"
        )
        machine.succeed("umount /mnt/edos-volume")
    machine.succeed("cryptsetup close edos-crypt")
  '';
}
