{ ... }:

{
  home.username = "forge";
  home.homeDirectory = "/home/forge";

  # Do not automatically advance this when changing Home Manager versions.
  home.stateVersion = "26.05";

  xdg.enable = true;

  # Own only an eduardOS-specific marker. In particular, do not manage
  # ~/.config/isenguard or ~/.config/opencode in this first migration.
  xdg.configFile."eduardos/managed-by-home-manager".text = ''
    eduardOS user configuration: Home Manager
    profile: forge-vm
  '';
}
