{ ... }:

{
  networking.hostName = "eduardos-vm";

  # QEMU VM prototype only. No physical disk partitioning or encryption.
  virtualisation.vmVariant.virtualisation = {
    memorySize = 4096;
    cores = 4;
    graphics = true;
  };

  # VM-only credentials, NEVER use on a physical installation.
  users.users.forge = {
    isNormalUser = true;
    initialPassword = "forge";
    extraGroups = [ "wheel" "networkmanager" ];
  };

  # This version is for an initial NixOS 26.05 install; don't bump
  # stateVersion automatically when updating inputs.
  system.stateVersion = "26.05";
}
