{ pkgs, lib, targetSystem, formattingSystem, labExecutor, mountAuditor }:

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
        labExecutor
        mountAuditor
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
    # qemu-vm.nix serializes its root disk as "root": stable by-id identity.
    # /dev/vda is only the disposable VM disk, never a physical target.
    installer.succeed("test -L /dev/disk/by-id/virtio-root")
    installer.succeed("test \"$(readlink -f /dev/disk/by-id/virtio-root)\" = /dev/vda")

    with subtest("Partition through the real Disko layout"):
        installer.succeed(
            "umask 077; printf 'edos-disposable-test-passphrase' "
            "> /run/edos-test-passphrase"
        )
        # The lab executor runs Disko and nixos-install only after
        # checking an explicit QEMU-only marker, target disk state and
        # an exact human-readable confirmation.
        installer.succeed(
            "printf 'EDOS-LAB-ONLY' > /run/eduardos-disposable-install-lab"
        )
        # This string is PUBLIC, disposable test-only data, never a real
        # password. It lives under the test guest's /run tmpfs and is
        # supplied through stdin, never a process argument to the helper.
        installer.succeed(
            "umask 077; printf 'edos-QEMU-public-login-fixture-32' "
            "> /run/edos-public-user-password"
        )
        # Reject missing password input BEFORE Disko erases the test disk.
        installer.fail(
            "${lib.getExe labExecutor} --execute "
            "--confirm 'ERASE DISPOSABLE /dev/vda' "
            "--user-password-stdin </dev/null"
        )
        installer.succeed("test ! -e /dev/vda1")
        installer.succeed(
            "${lib.getExe labExecutor} --execute "
            "--confirm 'ERASE DISPOSABLE /dev/vda' --user-password-stdin "
            "</run/edos-public-user-password"
        )
        installer.succeed("rm /run/edos-public-user-password")
        installer.succeed("test -s /mnt/persist/eduardos/credentials/testpilot.hash")
        installer.succeed(
            "test \"$(stat -c %a /mnt/persist/eduardos/credentials/testpilot.hash)\" = 600"
        )
        installer.succeed(
            "test \"$(stat -c %a /mnt/persist/eduardos/credentials)\" = 700"
        )
        installer.succeed("cryptsetup isLuks --type luks2 /dev/vda2")
        # The lab executor now performs the mount audit BEFORE nixos-install.
        # Re-run it explicitly against live kernel topology for evidence.
        installer.succeed("${lib.getExe mountAuditor} --disk /dev/vda")
        installer.fail("${lib.getExe mountAuditor} --disk /dev/vdb")
        installer.succeed("findmnt /mnt")
        installer.succeed("findmnt /mnt/boot")
        for p in ["home", "nix", "persist", ".snapshots"]:
            installer.succeed(f"findmnt /mnt/{p}")

    with subtest("Verify installed eduardOS UEFI system closure"):
        installer.succeed("mkdir -p /mnt/home/edos-test")
        installer.succeed("printf 'home-survived' > /mnt/home/edos-test/marker")
        installer.succeed("printf 'persist-survived' > /mnt/persist/marker")
        installer.succeed("test -f /mnt/boot/loader/loader.conf")
        installer.succeed("test -d /mnt/boot/EFI")
        installer.succeed("test ! -e /mnt/persist/eduardos/credentials/forge.hash")
        installer.succeed("sync")
        installer.succeed("umount -R /mnt")
        installer.fail("${lib.getExe mountAuditor} --disk /dev/vda")
        installer.shutdown()

    # Exactly the same qcow2 now booted using firmware, not a direct kernel.
    target.state_dir = installer.state_dir

    def boot_and_unlock():
        target.start()
        # The prompt may be rendered without a newline and the test
        # driver's line-oriented matcher can miss it even though QEMU's
        # serial log has received it. Inspect accumulated serial output
        # instead; do not bypass the interactive LUKS unlock.
        import time
        for attempt in range(180):
            console = target.get_console_log()
            if "Starting password query on /dev/ttyS0" in console:
                break
            time.sleep(1)
        else:
            raise AssertionError(
                "LUKS serial password agent did not appear; final log:\\n"
                + target.get_console_log()[-6000:]
            )
        target.send_console("edos-disposable-test-passphrase\n")
        target.wait_for_unit("multi-user.target", timeout=180)
        target.succeed("test -e /dev/mapper/edos-crypt")
        target.succeed("findmnt -n -o FSTYPE / | grep -Fx btrfs")
        target.succeed("findmnt -n -o FSTYPE /boot | grep -Fx vfat")
        target.succeed("test -x /run/current-system/sw/bin/Hyprland")
        target.succeed("test -x /run/current-system/sw/bin/ghostty")
        target.succeed("systemctl is-active NetworkManager.service")
        target.succeed("test -s /etc/xdg/eduardos/forge-classic-wallpaper.jpg")
        target.succeed("getent passwd testpilot")
        target.fail("getent passwd forge")
        target.succeed("systemctl is-active greetd.service")
        target.succeed("test -d /home/testpilot")
        target.succeed("test -s /persist/eduardos/credentials/testpilot.hash")
        target.succeed("grep -q '^testpilot:[$]6[$]' /etc/shadow")

    with subtest("Boot installed system via OVMF and unlock LUKS"):
        boot_and_unlock()
        target.succeed("grep -Fxq home-survived /home/edos-test/marker")
        target.succeed("grep -Fxq persist-survived /persist/marker")
        # greetd is a privileged login daemon. Test its actual PAM
        # service as root, just as greetd invokes PAM, rather than as
        # 'nobody': linux-pam's unix_chkpwd cannot authenticate another
        # account when the calling process is unprivileged, and reports
        # "user unknown" even with a valid installed password hash.
        # pamtester explicitly performs the password challenge; this is
        # NOT root's passwordless 'su'. The credential is PUBLIC test data.
        target.succeed(
            "echo 'edos-QEMU-public-login-fixture-32' "
            "| pamtester greetd testpilot authenticate"
        )
        target.fail(
            "echo 'incorrect-disposable-fixture' "
            "| pamtester greetd testpilot authenticate"
        )
        # Also exercise the traditional console login PAM policy.
        target.succeed(
            "echo 'edos-QEMU-public-login-fixture-32' "
            "| pamtester login testpilot authenticate"
        )
        target.fail(
            "echo 'incorrect-disposable-fixture' "
            "| pamtester login testpilot authenticate"
        )
        target.succeed(
            "runuser -u testpilot -- sh -c "
            "'printf user-data-retained > /home/testpilot/.edos-login-marker'"
        )
        target.succeed("printf 'second-boot' > /home/edos-test/second-marker")
        target.shutdown()

    with subtest("Cold boot again and verify encrypted persistent data"):
        boot_and_unlock()
        target.succeed("grep -Fxq home-survived /home/edos-test/marker")
        target.succeed("grep -Fxq second-boot /home/edos-test/second-marker")
        target.succeed("grep -Fxq persist-survived /persist/marker")
        target.succeed(
            "grep -Fxq user-data-retained /home/testpilot/.edos-login-marker"
        )
        target.succeed("test -s /persist/eduardos/credentials/testpilot.hash")
  '';
}
