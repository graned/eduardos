{ ... }:

{
  # This account exists exclusively for the disposable QEMU VM and tests.
  # Never import this module into a physical installation.
  users.users.forge = {
    isNormalUser = true;
    initialPassword = "forge";
    extraGroups = [ "wheel" "networkmanager" ];
  };

  home-manager.useGlobalPkgs = true;
  home-manager.useUserPackages = true;
  home-manager.users.forge = import ../../home/forge.nix;
}
