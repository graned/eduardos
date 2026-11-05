{ pkgs, lib, targetSystem, formattingSystem }:

# Install eduardOS onto a throwaway disk; boot that disk via OVMF.
pkgs.testers.runNixOSTest {
  name = "eduardos-installed-uefi-luks-boot";
  meta.timeout = 1800;

  nodes = {
    installer = { ... }: {
      nix.enable = true;
      networking.hostName = "edos-installer-test";

      # Only one VM runs at a time; both use this one on-disk image.
      virtualisation.diskImage = "./edos-installed-target.qcow2";
      virtualisation.diskSize = 12 * 1024;
      virtualisation.emptyDiskImages = [ 1024 ];
      virtualisation.rootDevice = "/dev/vdb";
      # The installer boots from its own temporary /dev/vdb, not the
      # target disk /dev/vda. Initialize that temporary root in initrd.
      boot.initrd.systemd.enable = true;
      virtualisation.fileSystems."/".autoFormat = true;
      virtualisation.memorySize = 4096;
      virtualisation.cores = 4;

      system.extraDependencies = [
        targetSystem.config.system.build.toplevel
        formattingSystem.config.system.build.destroyFormatMount
        pkgs.stdenv
        pkgs.perlPackages.ConfigIniFiles
        pkgs.perlPackages.FileSlurp
      ];

      environment.systemPackages = with pkgs; [
        cryptsetup btrfs-progs parted util-linux nixos-install-tools
      ];
      boot.supportedFilesystems = [ "btrfs" "vfat" ];
      boot.loader.grub.enable = false;
      system.stateVersion = "26.05";
    };

    target = { ... }: {
      networking.hostName = "edos-installed-target-test";
      system.stateVersion = "26.05";
      virtualisation.diskImage = "./edos-installed-target.qcow2";
      virtualisation.diskSize = 12 * 1024;
      virtualisation.memorySize = 4096;
      virtualisation.cores = 4;
      virtualisation.useBootLoader = true;
      virtualisation.useEFIBoot = true;
      virtualisation.useDefaultFilesystems = false;
      virtualisation.efi.keepVariables = false;

      # Runner's fake root is never used: OVMF loads the installed OS.
      virtualisation.fileSystems."/" = {
        device = "/dev/disk/by-label/UNUSED-TEST-RUNNER-ROOT";
        fsType = "ext4";
      };
    };
  };

  testScript = ''
    installer.start()
    installer.wait_for_unit("multi-user.target")
    installer.wait_until_succeeds("test -b /dev/vda && test -b /dev/vdb")
    installer.succeed("lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS")

    with subtest("Partition through the real Disko layout"):
        installer.succeed(
            "umask 077; printf 'edos-disposable-test-passphrase' "
            "> /run/edos-test-passphrase"
        )
        installer.succeed(
            "${lib.getExe formattingSystem.config.system.build.destroyFormatMount} "
            "--yes-wipe-all-disks"
        )
        installer.succeed("cryptsetup isLuks --type luks2 /dev/vda2")
        installer.succeed("findmnt /mnt")
        installer.succeed("findmnt /mnt/boot")
        for p in ["home", "nix", "persist", ".snapshots"]:
            installer.succeed(f"findmnt /mnt/{p}")

    with subtest("Install actual eduardOS UEFI system closure"):
        installer.succeed("mkdir -p /mnt/home/edos-test")
        installer.succeed("printf 'home-survived' > /mnt/home/edos-test/marker")
        installer.succeed("printf 'persist-survived' > /mnt/persist/marker")
        installer.succeed(
            "nixos-install --root /mnt "
            "--system ${targetSystem.config.system.build.toplevel} "
            "--no-root-passwd < /dev/null >&2"
        )
        installer.succeed("test -f /mnt/boot/loader/loader.conf")
        installer.succeed("test -d /mnt/boot/EFI")
        installer.succeed("sync")
        installer.succeed("umount -R /mnt")
        installer.shutdown()

    # Exactly the same qcow2 now booted using firmware, not a direct kernel.
    target.state_dir = installer.state_dir

    def boot_and_unlock():
        target.start()
        target.wait_for_console_text("passphrase for", timeout=180)
        target.send_console("edos-disposable-test-passphrase\\n")
        target.wait_for_unit("multi-user.target", timeout=180)
        target.succeed("test -e /dev/mapper/edos-crypt")
        target.succeed("findmnt -n -o FSTYPE / | grep -Fx btrfs")
        target.succeed("findmnt -n -o FSTYPE /boot | grep -Fx vfat")
        target.succeed("test -x /run/current-system/sw/bin/Hyprland")
        target.succeed("test -x /run/current-system/sw/bin/ghostty")
        target.succeed("systemctl is-active NetworkManager.service")
        target.succeed("test -s /etc/xdg/eduardos/forge-classic-wallpaper.jpg")

    with subtest("Boot installed system via OVMF and unlock LUKS"):
        boot_and_unlock()
        target.succeed("grep -Fxq home-survived /home/edos-test/marker")
        target.succeed("grep -Fxq persist-survived /persist/marker")
        target.succeed("printf 'second-boot' > /home/edos-test/second-marker")
        target.shutdown()

    with subtest("Cold boot again and verify encrypted persistent data"):
        boot_and_unlock()
        target.succeed("grep -Fxq home-survived /home/edos-test/marker")
        target.succeed("grep -Fxq second-boot /home/edos-test/second-marker")
        target.succeed("grep -Fxq persist-survived /persist/marker")
  '';
}
