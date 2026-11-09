{
  description = "eduardOS — Forged in Chaos: Obsidian Forge desktop";

  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-26.05/nixexprs.tar.zst";
  inputs.home-manager = {
    url = "github:nix-community/home-manager/release-26.05";
    inputs.nixpkgs.follows = "nixpkgs";
  };
  inputs.disko = {
    url = "github:nix-community/disko/latest";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, home-manager, disko }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      desktopModules = [
        ./nix/modules/core.nix
        ./nix/modules/desktop/hyprland.nix
        ./nix/modules/desktop/obsidian-forge.nix
        ./nix/modules/development/shell.nix
        ./nix/modules/development/opencode.nix
        ./nix/modules/development/isenguard.nix
      ];
      vmModules = desktopModules ++ [
        home-manager.nixosModules.home-manager
        ./hosts/virtual-machine/user.nix
      ];
      # The end-to-end installation test uses a QEMU-instrumented instance
      # of the very same UEFI storage/desktop configuration.
      installedLabModules = desktopModules ++ [
        disko.nixosModules.disko
        ./nix/storage/disko-layout.nix
        ./hosts/uefi-lab/default.nix
        ({ modulesPath, ... }: {
          imports = [
            (modulesPath + "/testing/test-instrumentation.nix")
            (modulesPath + "/profiles/qemu-guest.nix")
          ];
          boot.loader.systemd-boot.graceful = true;
          documentation.enable = false;
        })
      ];
      installedLabSystem = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = installedLabModules;
      };
      # Only Disko's *formatting* script reads the ephemeral runtime file.
      # The installed system still requires interactive unlock at every boot.
      installerFormatSystem = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = installedLabModules ++ [
          { disko.devices.disk.system.content.partitions.encrypted.content.passwordFile =
              "/run/edos-test-passphrase"; }
        ];
      };
      # Factory for a real installed-system closure. No default target disk,
      # username, or hostname. It only evaluates NixOS; never runs Disko.
      mkInstalledSystem = { diskDevice, username, hostname }:
        assert builtins.isString diskDevice
          && builtins.match "/dev/disk/by-id/[a-zA-Z0-9_.:+-]+" diskDevice != null;
        assert builtins.isString username
          && builtins.match "[a-z_][a-z0-9_-]{0,30}" username != null
          && !(builtins.elem username [ "root" "nixbld" "forge" "greeter" ]);
        assert builtins.isString hostname
          && builtins.match "[a-z][a-z0-9-]{0,62}" hostname != null
          && !(nixpkgs.lib.hasSuffix "-" hostname);
        nixpkgs.lib.nixosSystem {
          inherit system;
          specialArgs = { inherit diskDevice username hostname; };
          modules = desktopModules ++ [
            disko.nixosModules.disko
            home-manager.nixosModules.home-manager
            ./nix/storage/disko-layout.nix
            ./hosts/installed/default.nix
          ];
        };
      # A non-existent by-id path is ONLY used for pure evaluation.
      # This is not an installer target and must never be provisioned.
      installedFixture = mkInstalledSystem {
        diskDevice = "/dev/disk/by-id/wwn-0xEDOS-NONEXISTENT-FIXTURE";
        username = "testpilot";
        hostname = "edos-installed-preview";
      };
      forgeInstaller = pkgs.writeShellApplication {
        name = "forge-installer";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer/forge_installer.py} "$@"
        '';
      };
      forgeInstallerGui = pkgs.writeShellApplication {
        name = "forge-installer-gui";
        runtimeInputs = with pkgs; [ python3 util-linux xdg-utils ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_gui.py "$@"
        '';
      };
      # Lab-only destructive installer, permanently hard-locked to a
      # disposable QEMU /dev/vda. Not part of live ISO or GUI packages.
      forgeInstallerLab = pkgs.writeShellApplication {
        name = "forge-installer-lab";
        runtimeInputs = with pkgs; [ python3 util-linux nixos-install-tools ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_executor_lab.py \
            --disko-script ${nixpkgs.lib.getExe installerFormatSystem.config.system.build.destroyFormatMount} \
            --system-closure ${installedLabSystem.config.system.build.toplevel} "$@"
        '';
      };
      # Read-only production disk identity contract. No privileged helper
      # and no disk writes; it cannot invoke the lab executor.
      forgeDiskReview = pkgs.writeShellApplication {
        name = "forge-disk-review";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_disk_identity.py "$@"
        '';
      };
      # Read-only ephemeral authorization rehearsal. NOT an installer.
      forgeAuthorization = pkgs.writeShellApplication {
        name = "forge-authorization";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_authorization.py "$@"
        '';
      };
      # Read-only live ISO backing chain audit. It is intentionally
      # separate from the installer and cannot enable disk writes.
      forgeLiveMedia = pkgs.writeShellApplication {
        name = "forge-live-media";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_live_media_cli.py "$@"
        '';
      };
      # Read-only audit of an ALREADY mounted encrypted target; no formatting
      # or account-credential staging. Used in disposable QEMU integration.
      forgeMountAuditor = pkgs.writeShellApplication {
        name = "forge-mount-audit";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_mount_audit.py "$@"
        '';
      };
      # Root-only, read-only protection for active-system backing disks.
      forgePrivilegedPreflight = pkgs.writeShellApplication {
        name = "forge-privileged-preflight";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_privileged_guard.py "$@"
        '';
      };
      storageProvisioner = pkgs.writeShellApplication {
        name = "edos-storage-provision";
        runtimeInputs = with pkgs; [
          parted cryptsetup btrfs-progs dosfstools util-linux systemd
        ];
        text = builtins.readFile ./nix/storage/provision.sh;
      };
    in
    {
      # Public parameterized constructor for future installer integration;
      # no preselected target disk or shared demo credentials.
      lib.${system}.mkInstalledSystem = mkInstalledSystem;

      # Lab-only configuration: fully declarative UEFI + encrypted Btrfs.
      # Never point this at a real disk: device=/dev/vda is a QEMU fixture.
      nixosConfigurations.eduardos-uefi-lab = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = desktopModules ++ [
          disko.nixosModules.disko
          ./nix/storage/disko-layout.nix
          ./hosts/uefi-lab/default.nix
        ];
      };

      # Alpha 0.1 is a live ISO only: no Disko, target drive or installer.
      nixosConfigurations.eduardos-live = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = desktopModules ++ [
          ./hosts/live-iso/default.nix
        ];
      };

      nixosConfigurations.eduardos-vm = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = vmModules ++ [
          ./hosts/virtual-machine/default.nix
        ];
      };

      packages.${system} = {
        vm = self.nixosConfigurations.eduardos-vm.config.system.build.vm;
        live-iso = self.nixosConfigurations.eduardos-live.config.system.build.isoImage;
        storage-provision = storageProvisioner;
        forge-installer = forgeInstaller;
        forge-installer-gui = forgeInstallerGui;
        forge-installer-lab = forgeInstallerLab;
        forge-disk-review = forgeDiskReview;
        forge-authorization = forgeAuthorization;
        forge-privileged-preflight = forgePrivilegedPreflight;
        forge-live-media = forgeLiveMedia;
        forge-mount-audit = forgeMountAuditor;
      };

      checks.${system} = {
        # Trust-boundary fixtures: no root, no disk, no ISO or mount actions.
        forge-backend-tests = pkgs.runCommand "forge-backend-tests" {
          nativeBuildInputs = [ pkgs.python3 pkgs.openssl ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_backend.py' -v
          mkdir -p "$out"
          echo "Forge trusted target backend fixtures passed" > "$out/result"
        '';
        # Secure credential staging and LUKS FD tests use only a temporary
        # filesystem, unprivileged sandbox, and OpenSSL (no real disks/ISO).
        forge-credentials-tests = pkgs.runCommand "forge-credentials-tests" {
          nativeBuildInputs = [ pkgs.python3 pkgs.openssl ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_credentials.py' -v
          mkdir -p "$out"
          echo "Credential provisioning fixtures passed" > "$out/result"
        '';

        # Evaluate the real installed-system module using a deliberately
        # non-existent by-id fixture; no disk writes or closure/ISO builds.
        installed-profile-config =
          let
            cfg = installedFixture.config;
            user = cfg.users.users.testpilot;
            mounts = [ "/" "/boot" "/home" "/nix" "/persist" "/.snapshots" ];
            disk = cfg.disko.devices.disk.system;
            checks = [
              (cfg.networking.hostName == "edos-installed-preview")
              (disk.device == "/dev/disk/by-id/wwn-0xEDOS-NONEXISTENT-FIXTURE")
              (cfg.eduardos.storage.allowUnstableDeviceName == false)
              (builtins.all (p: builtins.hasAttr p cfg.fileSystems) mounts)
              (disk.content.partitions.encrypted.content.type == "luks")
              (disk.content.partitions.encrypted.content.content.type == "btrfs")
              (cfg.boot.loader.systemd-boot.enable)
              (cfg.boot.initrd.systemd.enable)
              (!cfg.users.mutableUsers)
              (user.hashedPasswordFile == "/persist/eduardos/credentials/testpilot.hash")
              (user.initialPassword == null)
              (user.hashedPassword == null)
              (cfg.users.users.root.hashedPassword == "!")
              (!(builtins.hasAttr "forge" cfg.users.users))
              (cfg.services.greetd.enable)
              (cfg.services.greetd.settings.default_session.user == "greeter")
              (cfg.security.sudo.wheelNeedsPassword)
              (cfg.home-manager.users.testpilot.home.username == "testpilot")
              (cfg.home-manager.users.testpilot.home.homeDirectory == "/home/testpilot")
              (!(builtins.tryEval ((mkInstalledSystem {
                diskDevice = "/dev/vda";
                username = "testpilot";
                hostname = "edos-preview";
              }).config.networking.hostName)).success)
              (!(builtins.tryEval ((mkInstalledSystem {
                diskDevice = "/dev/disk/by-id/wwn-0xNONEXISTENT";
                username = "forge";
                hostname = "edos-preview";
              }).config.networking.hostName)).success)
              (!(builtins.tryEval ((mkInstalledSystem {
                diskDevice = "/dev/disk/by-id/wwn-0xNONEXISTENT";
                username = "testpilot";
                hostname = "INVALID.HOST";
              }).config.networking.hostName)).success)
            ];
          in assert builtins.all (x: x) checks;
          pkgs.runCommand "eduardos-installed-profile-eval" {} ''
            mkdir -p "$out"
            echo "Installed target profile evaluated without any real disk" > "$out/result"
          '';
        # Pure Python kernel mount/loop provenance fixtures, no ISO build.
        forge-live-media-tests = pkgs.runCommand "forge-live-media-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_live_media.py' -v
          mkdir -p "$out"
          echo "Forge live media safety fixtures passed" > "$out/result"
        '';
        # Synthetic LUKS/RAID and mount graph tests; no real disks or ISO.
        forge-privileged-preflight-tests = pkgs.runCommand "forge-privileged-preflight-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_privileged_guard.py' -v
          mkdir -p "$out"
          echo "Privileged preflight ancestry tests passed" > "$out/result"
        '';
        # Authorization is read-only and exercised entirely via fixtures.
        forge-authorization-tests = pkgs.runCommand "forge-authorization-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_authorization.py' -v
          mkdir -p "$out"
          echo "Authorization and credential validation fixtures passed" > "$out/result"
        '';
        # Disk identity and stale-review tests use synthetic devices;
        # no root access, ISO compilation or actual disks.
        forge-disk-review-tests = pkgs.runCommand "forge-disk-review-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_disk_identity.py' -v
          mkdir -p "$out"
          echo "Read-only disk identity tests passed" > "$out/result"
        '';
        # Fail-closed lab executor unit tests, never touch the runner's disks.
        forge-installer-lab-tests = pkgs.runCommand "forge-installer-lab-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_executor_lab.py' -v
          mkdir -p "$out"
          echo "VM lab executor guard tests passed" > "$out/result"
        '';
        # Graphical browser wizard and API security fixtures, no ISO build.
        forge-installer-gui-tests = pkgs.runCommand "forge-installer-gui-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_gui.py' -v
          mkdir -p "$out"
          echo "Read-only GUI security and API tests passed" > "$out/result"
        '';

        # Read-only installation preflight, tested with synthetic block
        # devices. No ISO build, root privileges or real disks required.
        forge-installer-tests = pkgs.runCommand "forge-installer-tests" {
          nativeBuildInputs = [ pkgs.python3 pkgs.openssl ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_*.py' -v
          mkdir -p "$out"
          echo "Installer read-only fixture tests passed" > "$out/result"
        '';
        # Evaluate the ISO wiring on every PR without building a multi-GB ISO.
        live-iso-config =
          let
            cfg = self.nixosConfigurations.eduardos-live.config;
            hasIso = cfg.system.build ? isoImage;
            neon = cfg.eduardos.theme == "forge-neon";
            login = cfg.services.greetd.settings.initial_session.user == "forge";
            network = cfg.networking.networkmanager.enable;
            noDisko = !(cfg ? disko);
          in assert hasIso && neon && login && network && noDisko;
          pkgs.runCommand "eduardos-live-iso-config-check" {} ''
            mkdir -p "$out"
            echo "Live ISO configured without Disko" > "$out/result"
          '';

        # Build the NixOS installation closure, including systemd-boot,
        # initrd cryptsetup and generated mount definitions. This is not
        # yet a booted installation test.
        uefi-install-config = self.nixosConfigurations.eduardos-uefi-lab.config.system.build.toplevel;
        uefi-storage-layout =
          let
            cfg = self.nixosConfigurations.eduardos-uefi-lab.config;
            required = [ "/" "/boot" "/home" "/nix" "/persist" "/.snapshots" ];
            generated = builtins.attrNames cfg.fileSystems;
            correctMounts = builtins.all (p: builtins.elem p generated) required;
            disk = cfg.disko.devices.disk.system;
            correctDisk = disk.device == "/dev/vda";
            correctBoot = cfg.boot.loader.systemd-boot.enable;
            usesLuks = disk.content.partitions.encrypted.content.type == "luks";
            luksBtrfs = disk.content.partitions.encrypted.content.content.type == "btrfs";
          in assert correctMounts && correctDisk && correctBoot && usesLuks && luksBtrfs;
          pkgs.runCommand "eduardos-uefi-disko-config-validation" {} ''
            mkdir -p "$out"
            echo "Validated: GPT/EFI/LUKS2/Btrfs and six mounts" > "$out/result"
          '';
        uefi-installed-boot = import ./nix/tests/uefi-installed-boot.nix {
          inherit pkgs;
          lib = nixpkgs.lib;
          targetSystem = installedLabSystem;
          formattingSystem = installerFormatSystem;
          labExecutor = forgeInstallerLab;
        };
        storage-persistence = import ./nix/tests/storage-persistence.nix {
          inherit pkgs;
          modules = vmModules;
          provisioner = storageProvisioner;
          mountAuditor = forgeMountAuditor;
        };
        # Evaluate and build the generated assets of every supported preset.
        # This catches invalid choices or broken recoloring without booting
        # three complete VMs.
        theme-presets =
          let
            themeStyles = name:
              (nixpkgs.lib.nixosSystem {
                inherit system;
                modules = vmModules ++ [
                  { eduardos.theme = name; system.stateVersion = "26.05"; }
                ];
              }).config.environment.etc."xdg/waybar/style.css".source;
          in pkgs.runCommand "eduardos-theme-presets" {
            classic = themeStyles "forge-classic";
            neon = themeStyles "forge-neon";
            brutalist = themeStyles "forge-brutalist";
            neonWallpaper = (nixpkgs.lib.nixosSystem {
              inherit system;
              modules = vmModules ++ [
                { eduardos.theme = "forge-neon"; system.stateVersion = "26.05"; }
              ];
            }).config.environment.etc."xdg/eduardos/forge-neon-wallpaper.jpg".source;
            neonHyprland = (nixpkgs.lib.nixosSystem {
              inherit system;
              modules = vmModules ++ [
                { eduardos.theme = "forge-neon"; system.stateVersion = "26.05"; }
              ];
            }).config.environment.etc."xdg/hypr/hyprland.conf".source;
            neonGhostty = (nixpkgs.lib.nixosSystem {
              inherit system;
              modules = vmModules ++ [
                { eduardos.theme = "forge-neon"; system.stateVersion = "26.05"; }
              ];
            }).config.environment.etc."xdg/ghostty/config".source;
            brutalistWallpaper = (nixpkgs.lib.nixosSystem {
              inherit system;
              modules = vmModules ++ [
                { eduardos.theme = "forge-brutalist"; system.stateVersion = "26.05"; }
              ];
            }).config.environment.etc."xdg/eduardos/forge-brutalist-wallpaper.jpg".source;
            brutalistHyprland = (nixpkgs.lib.nixosSystem {
              inherit system;
              modules = vmModules ++ [
                { eduardos.theme = "forge-brutalist"; system.stateVersion = "26.05"; }
              ];
            }).config.environment.etc."xdg/hypr/hyprland.conf".source;
            brutalistGhostty = (nixpkgs.lib.nixosSystem {
              inherit system;
              modules = vmModules ++ [
                { eduardos.theme = "forge-brutalist"; system.stateVersion = "26.05"; }
              ];
            }).config.environment.etc."xdg/ghostty/config".source;
          } ''
            grep -Fq '#f18a4e' "$classic"
            grep -Fq '#19c6bf' "$neon"
            grep -Fq '#e6a04e' "$brutalist"
            test -s "$neonWallpaper"
            test "$(head -c 3 "$neonWallpaper" | od -An -tx1 | tr -d '[:space:]')" = ffd8ff
            grep -Fq 'exec-once = swaybg' "$neonHyprland"
            grep -Fq 'background-opacity = 0.88' "$neonGhostty"
            test -s "$brutalistWallpaper"
            test "$(head -c 3 "$brutalistWallpaper" | od -An -tx1 | tr -d '[:space:]')" = ffd8ff
            grep -Fq 'exec-once = swaybg' "$brutalistHyprland"
            grep -Fq 'col.active_border = rgba(e6a04eff)' "$brutalistHyprland"
            grep -Fq 'background-opacity = 0.89' "$brutalistGhostty"
            touch "$out"
          '';
        hyprland-session = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
        };
        theme-preview-classic = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
          theme = "forge-classic";
          preview = true;
        };
        theme-preview-neon = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
          theme = "forge-neon";
          preview = true;
        };
        theme-preview-brutalist = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
          theme = "forge-brutalist";
          preview = true;
        };

        boot = pkgs.testers.runNixOSTest {
        name = "eduardos-boot";
        nodes.machine = { ... }: {
          imports = vmModules;
          networking.hostName = "eduardos-test";
          system.stateVersion = "26.05";
        };
        testScript = ''
          machine.start()
          machine.wait_for_unit("multi-user.target")
          machine.succeed("uname -s | grep Linux")
          machine.succeed("systemctl is-active NetworkManager.service")
          machine.succeed("test -x /run/current-system/sw/bin/Hyprland")
          machine.succeed("test -x /run/current-system/sw/bin/brave")
          machine.succeed("test -x /run/current-system/sw/bin/zsh")
          machine.succeed("getent passwd forge | grep -q '/zsh$'")
          machine.succeed(
            "runuser -u forge -- zsh -ic 'print -r -- $ZSH_THEME' "
            "| grep -Fxq eduardos-catppuccin"
          )
          machine.succeed("test \"$(cat /etc/xdg/eduardos/theme)\" = forge-classic")
          machine.succeed("grep -Fq brave-browser.desktop /etc/xdg/mimeapps.list")
          machine.succeed("test -x /run/current-system/sw/bin/mpv")
          machine.succeed("opencode --version")
          # Home Manager must actually activate inside the guest.
          machine.wait_until_succeeds("test -f /home/forge/.config/eduardos/managed-by-home-manager")
          machine.succeed("grep -Fq 'profile: forge-vm' /home/forge/.config/eduardos/managed-by-home-manager")
          machine.succeed("env HOME=/tmp/edos-isenguard XDG_CONFIG_HOME=/tmp/edos-isenguard/config isenguard --version")
          machine.succeed("test -f /tmp/edos-isenguard/config/isenguard/init.lua")
          # Verify the actual desktop configuration lands in the booted guest.
          machine.succeed("test -r /etc/xdg/hypr/hyprland.conf")
          machine.succeed("grep -Fq 'exec-once = swaybg' /etc/xdg/hypr/hyprland.conf")
          machine.succeed("test -r /etc/xdg/eduardos/forge-classic-wallpaper.jpg")
          machine.succeed("test -s /etc/xdg/eduardos/forge-classic-wallpaper.jpg")
          machine.succeed("grep -Fq 'exec-once = waybar' /etc/xdg/hypr/hyprland.conf")
          machine.succeed("test -r /etc/xdg/waybar/config.jsonc")
          machine.succeed("test -r /etc/xdg/waybar/style.css")
          machine.succeed("test -r /etc/xdg/ghostty/config")
          machine.succeed("grep -Fqx 'background-opacity = 0.88' /etc/xdg/ghostty/config")
          machine.succeed("grep -Fqx 'background = #1e1e2e' /etc/xdg/ghostty/config")
          machine.succeed("test -r /etc/xdg/fuzzel/fuzzel.ini")
          machine.succeed("test -r /etc/xdg/mako/config")
        '';
      };
      };
    };
}
