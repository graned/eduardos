{ pkgs, ... }:

{
  programs.hyprland = {
    enable = true;
    withUWSM = true;
    xwayland.enable = true;
  };

  # The screenshot helper is shared by all themes and never saves to disk.
  environment.systemPackages = [
    (pkgs.writeShellApplication {
      name = "edos-screenshot";
      runtimeInputs = with pkgs; [ grim slurp wl-clipboard ];
      text = ''
        set -eu
        case "$1" in
          screen)
            grim - | wl-copy --type image/png
            ;;
          region)
            geometry="$(slurp)" || exit 0
            [ -n "$geometry" ] || exit 0
            grim -g "$geometry" - | wl-copy --type image/png
            ;;
          *)
            echo "Usage: edos-screenshot {screen|region}" >&2
            exit 2
            ;;
        esac
      '';
    })
  ];

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
