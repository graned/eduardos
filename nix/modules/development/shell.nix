{ pkgs, ... }:

{
  # Oh My Zsh is installed as part of the base developer experience.
  # User-specific shell dotfiles remain under user control.
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    ohMyZsh = {
      enable = true;
      theme = "eduardos-catppuccin";
      plugins = [ "git" ];
      custom = "${pkgs.writeTextDir "themes/eduardos-catppuccin.zsh-theme"
        (builtins.readFile ../../../themes/shell/eduardos-catppuccin.zsh-theme)}";
    };
  };

  # Applies to new users without an explicit shell override.
  users.defaultUserShell = pkgs.zsh;
}
