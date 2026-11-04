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
  classicPath = ../../../themes/forge-classic;
  wallpaper = pkgs.runCommand "eduardos-forge-classic-wallpaper.png" {
    nativeBuildInputs = [ pkgs.librsvg ];
  } ''
    rsvg-convert --width=1920 --height=1080 ${classicPath}/wallpaper.svg > "$out"
  '';
in
{
  options.eduardos.theme = lib.mkOption {
    type = lib.types.enum [ "forge-classic" "forge-neon" "forge-brutalist" ];
    default = "forge-classic";
    description = ''
      eduardOS Obsidian Forge appearance preset. This changes colors
      across desktop applications without changing their behavior.
    '';
  };

  config = {
    # System fallback configs: future user setup can select a theme by
    # setting eduardos.theme, while Home Manager overrides remain possible.
    environment.etc."xdg/hypr/hyprland.conf".source =
      if isClassic then classicPath + "/hyprland.conf" else themed "hyprland.conf" ../../../themes/obsidian-forge/hyprland.conf;
    environment.etc."xdg/waybar/config.jsonc".source =
      if isClassic then classicPath + "/waybar.json"
      else ../../../themes/obsidian-forge/waybar.json;
    environment.etc."xdg/waybar/style.css".source =
      if isClassic then classicPath + "/waybar.css" else themed "waybar.css" ../../../themes/obsidian-forge/waybar.css;
    environment.etc."xdg/fuzzel/fuzzel.ini".source =
      if isClassic then classicPath + "/fuzzel.ini" else themed "fuzzel.ini" ../../../themes/obsidian-forge/fuzzel.ini;
    environment.etc."xdg/mako/config".source =
      if isClassic then classicPath + "/mako.conf" else themed "mako.conf" ../../../themes/obsidian-forge/mako.conf;
    environment.etc."xdg/ghostty/config".source =
      if isClassic then classicPath + "/ghostty.conf" else themed "ghostty.conf" ../../../themes/obsidian-forge/ghostty.conf;
    environment.etc."xdg/eduardos/theme".text = config.eduardos.theme;
    environment.etc."xdg/eduardos/forge-classic-wallpaper.png" =
      lib.mkIf isClassic { source = wallpaper; };

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
    ]) ++ lib.optionals isClassic [ pkgs.swaybg ];
  };
}
