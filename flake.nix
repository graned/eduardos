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
        ({ ... }: { environment.systemPackages = [ edosCli ]; })
      ];
      # Rust CLI is read-only and standalone; Python Forge remains intact.
      # Restrict Cargo's build context so desktop/theme changes do not
      # invalidate the CLI derivation or increase CI disk usage.
      edosCli = pkgs.rustPlatform.buildRustPackage {
        pname = "edos";
        version = "0.1.0";
        src = pkgs.lib.fileset.toSource {
          root = ./.;
          fileset = pkgs.lib.fileset.unions [
            ./Cargo.toml
            ./Cargo.lock
            ./crates/edos
          ];
        };
        cargoLock.lockFile = ./Cargo.lock;
        cargoBuildFlags = [ "-p" "edos" ];
        cargoTestFlags = [ "-p" "edos" ];
        doCheck = true;
      };
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
      mkInstalledSystem = { diskDevice, username, hostname, extraModules ? [] }:
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
          ] ++ extraModules;
        };
      # A non-existent by-id path is ONLY used for pure evaluation.
      # This is not an installer target and must never be provisioned.
      installedFixture = mkInstalledSystem {
        diskDevice = "/dev/disk/by-id/wwn-0xEDOS-NONEXISTENT-FIXTURE";
        username = "testpilot";
        hostname = "edos-installed-preview";
      };
      # Disposable-VM-only exercise of the SAME installed profile factory.
      # The QEMU root block disk has serial "root" and thus the by-id
      # alias /dev/disk/by-id/virtio-root. Never use this on hardware.
      installedUserLabSystem = mkInstalledSystem {
        diskDevice = "/dev/disk/by-id/virtio-root";
        username = "testpilot";
        hostname = "edos-installed-lab";
        extraModules = [
          ({ modulesPath, ... }: {
            imports = [
              (modulesPath + "/testing/test-instrumentation.nix")
              (modulesPath + "/profiles/qemu-guest.nix")
            ];
            boot.loader.systemd-boot.graceful = true;
            documentation.enable = false;
            # PAM validation runs *inside* the installed disposable system.
            environment.systemPackages = [ pkgs.pamtester ];
          })
        ];
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
        runtimeInputs = with pkgs; [ python3 util-linux nixos-install-tools openssl ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_executor_lab.py \
            --disko-script ${nixpkgs.lib.getExe installerFormatSystem.config.system.build.destroyFormatMount} \
            --system-closure ${installedUserLabSystem.config.system.build.toplevel} "$@"
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
      # One-shot ROOT-ONLY read-only physical-target attestation contract.
      # Deliberately NOT in the live ISO, GUI or installer executable:
      # no daemon, privilege escalation, disk write or installation API.
      forgePrivilegedProtocol = pkgs.writeShellApplication {
        name = "forge-privileged-protocol";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_privileged_protocol.py "$@"
        '';
      };
      # Root-held, double-audited NON-EXECUTABLE physical install manifest.
      # No device writes, privileged writer, GUI bridge, or live ISO hook.
      forgePhysicalPreview = pkgs.writeShellApplication {
        name = "forge-physical-preview";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_physical_preview.py "$@"
        '';
      };
      # Manual root/physical-VT-only, ONE-SHOT read-only preflight.
      # Not installed in the live ISO, no systemd service, no polkit,
      # no GUI bridge, no credentials, no physical disk writer.
      forgeConsolePreflight = pkgs.writeShellApplication {
        name = "forge-console-preflight";
        runtimeInputs = with pkgs; [ python3 util-linux ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./installer}/forge_console_service.py "$@"
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
        edos = edosCli;
        vm = self.nixosConfigurations.eduardos-vm.config.system.build.vm;
        live-iso = self.nixosConfigurations.eduardos-live.config.system.build.isoImage;
        storage-provision = storageProvisioner;
        forge-installer = forgeInstaller;
        forge-installer-gui = forgeInstallerGui;
        forge-installer-lab = forgeInstallerLab;
        forge-disk-review = forgeDiskReview;
        forge-authorization = forgeAuthorization;
        forge-privileged-preflight = forgePrivilegedPreflight;
        forge-privileged-protocol = forgePrivilegedProtocol;
        forge-console-preflight = forgeConsolePreflight;
        forge-physical-preview = forgePhysicalPreview;
        forge-live-media = forgeLiveMedia;
        forge-mount-audit = forgeMountAuditor;
      };

      checks.${system} = {
        edos-cli-tests = edosCli;
        # Execute the packaged binary, not only Rust unit tests.
        edos-cli-smoke = pkgs.runCommand "edos-cli-smoke" {} ''
          ${edosCli}/bin/edos --version | grep -Fx "edos 0.1.0"
          ${edosCli}/bin/edos help | grep -F "Forged in Neon"
          ${edosCli}/bin/edos doctor | grep -F "Installer operations: unavailable"
          ${edosCli}/bin/edos status | grep -F "Mode: read-only"
          if ${edosCli}/bin/edos install 2>/dev/null; then
            echo "Unexpected installer command" >&2
            exit 1
          fi
          touch "$out"
        '';
        # Read-only mount audit fixtures, no actual block device opened.
        forge-mount-audit-tests = pkgs.runCommand "forge-mount-audit-tests" {
          nativeBuildInputs = [ pkgs.python3 pkgs.openssl ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_mount_audit.py' -v
          mkdir -p "$out"
          echo "Forge mounted-target auditor fixtures passed" > "$out/result"
        '';
        # Trust-boundary fixtures: no root, no disk, no ISO or mount actions.
        forge-backend-tests = pkgs.runCommand "forge-backend-tests" {
          nativeBuildInputs = [ pkgs.python3 pkgs.openssl ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_backend.py' -v
          mkdir -p "$out"
          echo "Forge trusted target backend fixtures passed" > "$out/result"
        '';
        # Static disposable-QEMU command allowlist and read-only
        # kernel mount/swap ancestry contract; no shell or disk writes.
        forge-lab-command-contract-tests = pkgs.runCommand "forge-lab-command-contract-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_lab_command_policy.py' -v
          mkdir -p "$out"
          echo "QEMU command contract and read-only irreversible-gate tests passed" > "$out/result"
        '';
        # One-shot root-consent + audited physical plan + two sealed
        # role-separated credential FDs. No daemon, writes, ISO or disk.
        forge-execution-rehearsal-tests = pkgs.runCommand "forge-execution-rehearsal-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_execution_rehearsal.py' -v
          mkdir -p "$out"
          echo "One-shot no-write execution and sealed FD integration passed" > "$out/result"
        '';
        # Read-only physical execution intent, double disk topology
        # audit and denied write/format authorization; no root or ISO build.
        forge-physical-preview-tests = pkgs.runCommand "forge-physical-preview-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_physical_preview.py' -v
          mkdir -p "$out"
          echo "Physical installation preview denies all writes" > "$out/result"
        '';
        # Physical console foreground VT and pidfd-pinned root-only
        # one-shot read-only launcher. All console/disk operations mocked.
        forge-console-preflight-tests = pkgs.runCommand "forge-console-preflight-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_console_service.py' -v
          mkdir -p "$out"
          echo "Foreground physical VT and pinned local peer tests passed" > "$out/result"
        '';
        # Trusted local read-only session, consent and root-controlled
        # Unix socket lifecycle; never launches a service or writes disks.
        forge-local-service-tests = pkgs.runCommand "forge-local-service-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_local_service.py' -v
          mkdir -p "$out"
          echo "One-shot read-only service policy and private socket tests passed" > "$out/result"
        '';
        # Exercise connected AF_UNIX SO_PEERCRED + SCM_RIGHTS handoff
        # with ephemeral sockets, an unprivileged child and Linux memfds.
        # No privileged daemon, physical disks, NixOS or ISO build.
        forge-local-ipc-tests = pkgs.runCommand "forge-local-ipc-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_local_ipc.py' -v
          mkdir -p "$out"
          echo "Kernel authenticated local credential FD boundary passed" > "$out/result"
        '';
        # Rehearse sealed LUKS/account FD handoff in-process: no root,
        # privileged transport, disk writes or system-image build.
        forge-secret-handoff-tests = pkgs.runCommand "forge-secret-handoff-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_secret_handoff.py' -v
          mkdir -p "$out"
          echo "Sealed one-shot credential FD handoff tests passed" > "$out/result"
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

        # Evaluate the actual user-profile closure for disposable QEMU only.
        # This does not build the closure or allocate a disk.
        installed-user-lab-config =
          let
            cfg = installedUserLabSystem.config;
            user = cfg.users.users.testpilot;
          in assert builtins.all (x: x) [
            (cfg.networking.hostName == "edos-installed-lab")
            (cfg.disko.devices.disk.system.device == "/dev/disk/by-id/virtio-root")
            (cfg.fileSystems."/persist".neededForBoot)
            (!cfg.users.mutableUsers)
            (cfg.users.users.root.hashedPassword == "!")
            (user.hashedPasswordFile == "/persist/eduardos/credentials/testpilot.hash")
            (user.initialPassword == null)
            (!(builtins.hasAttr "forge" cfg.users.users))
            (cfg.services.greetd.enable)
            (cfg.services.greetd.settings.default_session.user == "greeter")
            (cfg.security.sudo.wheelNeedsPassword)
            (cfg.home-manager.users.testpilot.home.homeDirectory == "/home/testpilot")
            (builtins.elem pkgs.pamtester cfg.environment.systemPackages)
          ];
          pkgs.runCommand "edos-installed-user-lab-config" {} ''
            mkdir -p "$out"
            echo "Real installed profile configured on disposable QEMU by-id only" > "$out/result"
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
              (cfg.fileSystems."/persist".neededForBoot)
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
        # Strict one-shot root-side JSON request protocol. All tests are
        # in-memory fixtures: no root, device handles, formatting or ISO.
        forge-privileged-protocol-tests = pkgs.runCommand "forge-privileged-protocol-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_privileged_protocol.py' -v
          mkdir -p "$out"
          echo "Versioned privileged request contract remains read-only" > "$out/result"
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
        # Real harmless subprocess cancellation, no disk/ISO required.
        forge-lab-child-tests = pkgs.runCommand "forge-lab-child-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_lab_child.py' -v
          mkdir -p "$out"
          echo "QEMU child cancellation fixtures passed" > "$out/result"
        '';
        # Same-boot one-shot lab format marker and read-only recovery
        # classification. Unit fixtures use only ephemeral ordinary files.
        forge-lab-attempt-tests = pkgs.runCommand "forge-lab-attempt-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_lab_attempt.py' -v
          mkdir -p "$out"
          echo "QEMU format attempt and read-only recovery fixtures passed" > "$out/result"
        '';
        # Pure one-shot transaction sequencing and failure injection.
        # No formatter, root privileges, mounted disks or ISO build.
        forge-install-transaction-tests = pkgs.runCommand "forge-install-transaction-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_install_transaction.py' -v
          mkdir -p "$out"
          echo "One-shot install transaction and failure gates passed" > "$out/result"
        '';
        # Fresh, read-only kernel mount/swap/device audit immediately
        # before QEMU-only Disko; mock all disk and subprocess operations.
        forge-irreversible-gate-tests = pkgs.runCommand "forge-irreversible-gate-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cd ${./installer}
          python3 -m unittest discover -p 'test_forge_irreversible_gate.py' -v
          mkdir -p "$out"
          echo "Disposable QEMU irreversible-boundary fail-closed tests passed" > "$out/result"
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
            serialProbe = cfg.systemd.services.edos-live-boot-probe.wantedBy
              == [ "multi-user.target" ];
            rustCli = builtins.any (pkg: (pkg.pname or "") == "edos")
              cfg.environment.systemPackages;
          in assert hasIso && neon && login && network && noDisko
            && serialProbe && rustCli;
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
        # Real-kernel adversarial root/non-root IPC test in a minimal
        # disposable NixOS VM. Runs in a separate parallel CI job.
        forge-local-adversarial = import ./nix/tests/forge-local-adversarial.nix {
          inherit pkgs;
        };
        # Real disposable QEMU disk: inject partial GPT write failure,
        # require terminal marker and refuse a second install invocation.
        forge-lab-failure-recovery = import ./nix/tests/forge-lab-failure-recovery.nix {
          inherit pkgs;
        };
        uefi-installed-boot = import ./nix/tests/uefi-installed-boot.nix {
          inherit pkgs;
          lib = nixpkgs.lib;
          targetSystem = installedUserLabSystem;
          formattingSystem = installerFormatSystem;
          labExecutor = forgeInstallerLab;
          mountAuditor = forgeMountAuditor;
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
