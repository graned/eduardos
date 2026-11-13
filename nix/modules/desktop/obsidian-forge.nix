{ config, lib, pkgs, ... }:

let
  # A single desktop layout/behavior, with three lightweight colorways.
  # Recolor the shipped Classic assets at evaluation time, not at runtime.
  palettes = {
    forge-classic = {
      void = "0b0d12";
      text = "e7e3dd";
      border = "303641";
      accent = "e56b35";
      highlight = "ffb366";
      signal = "40c9b6";
      surface = "1b202b";
      muted = "aab3c2";
    };
    forge-neon = {
      void = "090e14";
      text = "e5f4f2";
      border = "294751";
      accent = "19c6bf";
      highlight = "ffad57";
      signal = "e56b35";
      surface = "122a32";
      muted = "a0c2c9";
    };
    forge-eclipse = {
      void = "080709";
      text = "eee3dd";
      border = "4b2931";
      accent = "d43a45";
      highlight = "e7b18d";
      signal = "ba5362";
      surface = "21151a";
      muted = "b99ea1";
    };
    forge-brutalist = {
      void = "101113";
      text = "e8e8e5";
      border = "414449";
      accent = "ff8a45";
      highlight = "f4f1e9";
      signal = "b3b9bd";
      surface = "232527";
      muted = "b0b3b4";
    };
  };

  classic = palettes.forge-classic;
  selected = palettes.${config.eduardos.theme};
  colorFields = [ "void" "text" "border" "accent" "highlight" "signal" "surface" "muted" ];
  from = map (field: classic.${field}) colorFields;
  to = map (field: selected.${field}) colorFields;
  themed = name: file:
    pkgs.writeText "eduardos-${config.eduardos.theme}-${name}"
      (builtins.replaceStrings from to (builtins.readFile file));

  # Classic receives its own curated visual design while Neon and
  # Brutalist continue using the shared palette-based foundation.
  isClassic = config.eduardos.theme == "forge-classic";
  isNeon = config.eduardos.theme == "forge-neon";
  isBrutalist = config.eduardos.theme == "forge-brutalist";
  isEclipse = config.eduardos.theme == "forge-eclipse";
  classicPath = ../../../themes/forge-classic;
  neonPath = ../../../themes/forge-neon;
  brutalistPath = ../../../themes/forge-brutalist;
  eclipsePath = ../../../themes/forge-eclipse;
  eclipseWallpaper = import ../../artwork/forge-eclipse.nix { inherit pkgs; };
  # The approved artwork is rendered to PNG during the Nix build, never at login.
  wallpaper = classicPath + "/wallpaper.jpg";
in
{
  options.eduardos.theme = lib.mkOption {
    type = lib.types.enum [ "forge-classic" "forge-neon" "forge-brutalist" "forge-eclipse" ];
    default = "forge-eclipse";
    description = ''
      eduardOS Obsidian Forge appearance preset. This changes colors
      across desktop applications without changing their behavior.
    '';
  };

  config = {
    # System fallback configs: future user setup can select a theme by
    # setting eduardos.theme, while Home Manager overrides remain possible.
    environment.etc."xdg/hypr/hyprland.conf".source =
      if isClassic then classicPath + "/hyprland.conf"
      else if isNeon then neonPath + "/hyprland.conf"
      else if isBrutalist then brutalistPath + "/hyprland.conf"
      else if isEclipse then eclipsePath + "/hyprland.conf"
      else themed "hyprland.conf" ../../../themes/obsidian-forge/hyprland.conf;
    environment.etc."xdg/waybar/config.jsonc".source =
      if isClassic then classicPath + "/waybar.json"
      else if isNeon then neonPath + "/waybar.json"
      else if isBrutalist then brutalistPath + "/waybar.json"
      else if isEclipse then eclipsePath + "/waybar.json"
      else ../../../themes/obsidian-forge/waybar.json;
    environment.etc."xdg/waybar/style.css".source =
      if isClassic then classicPath + "/waybar.css"
      else if isNeon then neonPath + "/waybar.css"
      else if isBrutalist then brutalistPath + "/waybar.css"
      else if isEclipse then eclipsePath + "/waybar.css"
      else themed "waybar.css" ../../../themes/obsidian-forge/waybar.css;
    environment.etc."xdg/fuzzel/fuzzel.ini".source =
      if isClassic then classicPath + "/fuzzel.ini"
      else if isNeon then neonPath + "/fuzzel.ini"
      else if isBrutalist then brutalistPath + "/fuzzel.ini"
      else if isEclipse then eclipsePath + "/fuzzel.ini"
      else themed "fuzzel.ini" ../../../themes/obsidian-forge/fuzzel.ini;
    environment.etc."xdg/mako/config".source =
      if isClassic then classicPath + "/mako.conf"
      else if isNeon then neonPath + "/mako.conf"
      else if isBrutalist then brutalistPath + "/mako.conf"
      else if isEclipse then eclipsePath + "/mako.conf"
      else themed "mako.conf" ../../../themes/obsidian-forge/mako.conf;
    environment.etc."xdg/ghostty/config".source =
      if isClassic then classicPath + "/ghostty.conf"
      else if isNeon then neonPath + "/ghostty.conf"
      else if isBrutalist then brutalistPath + "/ghostty.conf"
      else if isEclipse then eclipsePath + "/ghostty.conf"
      else themed "ghostty.conf" ../../../themes/obsidian-forge/ghostty.conf;
    environment.etc."xdg/eduardos/theme".text = config.eduardos.theme;
    environment.etc."xdg/eduardos/forge-classic-wallpaper.jpg" =
      lib.mkIf isClassic { source = wallpaper; };
    environment.etc."xdg/eduardos/forge-neon-wallpaper.jpg" =
      lib.mkIf isNeon { source = neonPath + "/wallpaper.jpg"; };
    environment.etc."xdg/eduardos/forge-brutalist-wallpaper.jpg" =
      lib.mkIf isBrutalist { source = brutalistPath + "/wallpaper.jpg"; };

    environment.etc."xdg/eduardos/forge-eclipse-wallpaper.png" =
      lib.mkIf isEclipse { source = eclipseWallpaper + "/wallpaper.png"; };

    # Brave/Chromium under XWayland resolves both browser chrome and CSS
    # fallbacks through fontconfig; shipping fonts alone is insufficient
    # if a minimal live ISO doesn't advertise matching system defaults.
    fonts.fontconfig = {
      enable = true;
      defaultFonts = {
        sansSerif = [ "DejaVu Sans" ];
        serif = [ "DejaVu Serif" ];
        monospace = [ "DejaVu Sans Mono" ];
      };
    };
    fonts.packages = with pkgs; [
      dejavu_fonts
      nerd-fonts.jetbrains-mono
    ];

    environment.systemPackages = (with pkgs; [
      hyprpaper
      hyprlock
      hypridle
      pavucontrol
      brightnessctl
    ]) ++ lib.optionals (isClassic || isNeon || isBrutalist || isEclipse) [ pkgs.swaybg ];
  };
}
