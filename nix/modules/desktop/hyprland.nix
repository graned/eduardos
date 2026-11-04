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
    firefox
    mpv
  ];

  environment.sessionVariables.NIXOS_OZONE_WL = "1";
}
