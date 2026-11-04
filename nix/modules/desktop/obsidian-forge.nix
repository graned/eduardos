{ pkgs, ... }:

{
  # System defaults are deliberately placed under /etc/xdg:
  # future Home Manager profiles can override them per user.
  environment.etc."xdg/hypr/hyprland.conf".source =
    ../../../themes/obsidian-forge/hyprland.conf;
  environment.etc."xdg/waybar/config.jsonc".source =
    ../../../themes/obsidian-forge/waybar.json;
  environment.etc."xdg/waybar/style.css".source =
    ../../../themes/obsidian-forge/waybar.css;
  environment.etc."xdg/fuzzel/fuzzel.ini".source =
    ../../../themes/obsidian-forge/fuzzel.ini;
  environment.etc."xdg/mako/config".source =
    ../../../themes/obsidian-forge/mako.conf;
  environment.etc."xdg/ghostty/config".source =
    ../../../themes/obsidian-forge/ghostty.conf;

  fonts.packages = with pkgs; [
    dejavu_fonts
    nerd-fonts.jetbrains-mono
  ];

  environment.systemPackages = with pkgs; [
    hyprpaper
    hyprlock
    hypridle
    pavucontrol
    brightnessctl
  ];
}
