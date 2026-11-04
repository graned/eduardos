{ ... }:

{
  networking.hostName = "eduardos-vm";

  # QEMU's VM runner boots the kernel directly; this is not an
  # installable disk image or a configuration for physical hardware.
  boot.loader.grub.enable = false;

  # A temporary root filesystem for the disposable VM prototype.
  # The NixOS QEMU VM module manages its own writable guest state.
  fileSystems."/" = {
    device = "none";
    fsType = "tmpfs";
  };

  virtualisation.vmVariant.virtualisation = {
    memorySize = 4096;
    cores = 4;
    graphics = true;
  };

  # VM-only credentials. NEVER use these on a real installation.
  users.users.forge = {
    isNormalUser = true;
    initialPassword = "forge";
    extraGroups = [ "wheel" "networkmanager" ];
  };

  system.stateVersion = "26.05";
}
