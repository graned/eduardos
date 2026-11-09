{ lib, pkgs, username, hostname, diskDevice, ... }:

{
  # Target-system profile for future physical installation. This module
  # only describes a NixOS configuration; it never executes Disko.
  # All values are supplied explicitly by the caller, never guessed.
  assertions = [
    {
      assertion = builtins.isString username
        && builtins.match "[a-z_][a-z0-9_-]{0,30}" username != null
        && !(builtins.elem username [ "root" "nixbld" "forge" "greeter" ]);
      message = "eduardOS installed profile: explicit non-reserved lowercase user is required";
    }
    {
      assertion = builtins.isString hostname
        && builtins.match "[a-z][a-z0-9-]{0,62}" hostname != null
        && !(lib.hasSuffix "-" hostname);
      message = "eduardOS installed profile: a valid lowercase hostname is required";
    }
    {
      assertion = builtins.isString diskDevice
        && builtins.match "/dev/disk/by-id/[a-zA-Z0-9_.:+-]+" diskDevice != null;
      message = "eduardOS installed profile: disk must be a stable /dev/disk/by-id identifier";
    }
  ];

  networking.hostName = hostname;
  system.stateVersion = "26.05";

  # The exact same declarative Disko layout is used by the lab profile;
  # the installed target does NOT accept unstable /dev/sdX or /dev/vdX names.
  eduardos.storage.device = diskDevice;
  eduardos.storage.allowUnstableDeviceName = false;

  # Real hardware needs UEFI boot and an interactive unlock at startup.
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = false;
  boot.initrd.systemd.enable = true;
  boot.initrd.availableKernelModules = [
    "ahci"
    "nvme"
    "xhci_pci"
    "usb_storage"
    "sd_mod"
    "virtio_pci"
    "virtio_blk"
  ];
  services.fstrim.enable = true;

  # Unlike the live ISO, the installed system must NEVER auto-login.
  # greetd runs a visible local greeter before starting Hyprland.
  services.greetd = {
    enable = true;
    settings.default_session = {
      command = "${pkgs.greetd.tuigreet}/bin/tuigreet --time --cmd ${pkgs.hyprland}/bin/Hyprland";
      user = "greeter";
    };
  };

  # Initial credentials are an explicit dependency of the future trusted
  # installer. A password HASH is provisioned on the encrypted filesystem
  # at runtime; no secret material is put in Nix configuration/store.
  users.mutableUsers = false;
  users.users.root.hashedPassword = "!";
  users.users.${username} = {
    isNormalUser = true;
    extraGroups = [ "wheel" "networkmanager" "video" "audio" ];
    hashedPasswordFile = "/persist/eduardos/credentials/${username}.hash";
  };
  security.sudo.wheelNeedsPassword = true;

  home-manager.useGlobalPkgs = true;
  home-manager.useUserPackages = true;
  home-manager.users.${username} = import ../../home/installed.nix { inherit username; };
}
