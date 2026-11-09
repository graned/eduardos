{ username }:

{ ... }:

{
  # Installed accounts must not inherit the disposable VM's "forge" user.
  # This profile intentionally contains no password or authentication token.
  home.username = username;
  home.homeDirectory = "/home/${username}";
  home.stateVersion = "26.05";

  xdg.enable = true;

  # A minimal first-boot marker, not a hard-coded user configuration.
  # App-specific Home Manager modules can be added in later releases.
  xdg.configFile."eduardos/managed-by-home-manager".text = ''
    eduardOS installed profile
    user: ${username}
  '';
}
