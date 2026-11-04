{ pkgs, ... }:

{
  programs.hyprland = {
    enable = true;
    withUWSM = true;
    xwayland.enable = true;
  };

  # Hyprland's NixOS module provides the Wayland portal.
  environment.systemPackages = with pkgs; [
    ghostty
    waybar
    fuzzel
    mako
    wl-clipboard
    grim
    slurp
    brave
    mpv
  ];

  environment.sessionVariables = {
    NIXOS_OZONE_WL = "1";
    BROWSER = "brave";
  };

  # Set browser associations system-wide; users can override them in
  # their own XDG MIME configuration.
  xdg.mime.defaultApplications = {
    "text/html" = "brave-browser.desktop";
    "application/xhtml+xml" = "brave-browser.desktop";
    "x-scheme-handler/http" = "brave-browser.desktop";
    "x-scheme-handler/https" = "brave-browser.desktop";
  };
}
