{ lib, config, ... }:

{
  # The caller MUST select the target disk. Do not use a real-machine
  # default and do not silently infer the root drive.
  options.eduardos.storage = {
    device = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/dev/disk/by-id/nvme-EXAMPLE_DISK";
      description = ''
        Explicit target for the destructive Disko installation layout.
        Use stable /dev/disk/by-id paths on real hardware.
      '';
    };
    allowUnstableDeviceName = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Permit /dev/vda or similar device names only in disposable
        integration guests. Never enable this for physical installers.
      '';
    };
  };

  config = {
    assertions = [
      {
        assertion = config.eduardos.storage.device != null;
        message = "eduardOS: choose eduardos.storage.device explicitly before provisioning";
      }
      {
        assertion =
          config.eduardos.storage.device == null
          || config.eduardos.storage.allowUnstableDeviceName
          || lib.hasPrefix "/dev/disk/by-id/" config.eduardos.storage.device;
        message = ''
          eduardOS: real installations require a stable /dev/disk/by-id/
          path. Only disposable test guests may use unstable disk names.
        '';
      }
    ];

    disko.devices.disk.system = {
      type = "disk";
      device = config.eduardos.storage.device;
      content = {
        type = "gpt";
        partitions = {
          ESP = {
            priority = 1;
            size = "1G";
            type = "EF00";
            content = {
              type = "filesystem";
              format = "vfat";
              mountpoint = "/boot";
              mountOptions = [ "umask=0077" ];
            };
          };

          encrypted = {
            size = "100%";
            content = {
              type = "luks";
              name = "edos-crypt";
              # No keyFile: require an interactive LUKS passphrase.
              # Never store an unlock credential in the Nix store.
              settings.allowDiscards = false;
              content = {
                type = "btrfs";
                extraArgs = [ "-f" ];
                subvolumes = {
                  "/@root" = {
                    mountpoint = "/";
                    mountOptions = [ "compress=zstd" "noatime" ];
                  };
                  "/@home" = {
                    mountpoint = "/home";
                    mountOptions = [ "compress=zstd" "noatime" ];
                  };
                  "/@nix" = {
                    mountpoint = "/nix";
                    mountOptions = [ "compress=zstd" "noatime" ];
                  };
                  "/@persist" = {
                    mountpoint = "/persist";
                    mountOptions = [ "compress=zstd" "noatime" ];
                  };
                  "/@snapshots" = {
                    mountpoint = "/.snapshots";
                    mountOptions = [ "compress=zstd" "noatime" ];
                  };
                };
              };
            };
          };
        };
      };
    };
  };
}
