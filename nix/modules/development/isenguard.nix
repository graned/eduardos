{ pkgs, ... }:

let
  # Pinned upstream source revision.
  isenguardSource = builtins.fetchGit {
    url = "https://github.com/graned/isenguard.nvim.git";
    ref = "master";
    rev = "4a83a2626aef9ea6c992854ce37d0969cc9abf57";
  };

  isenguard = pkgs.writeShellApplication {
    name = "isenguard";

    runtimeInputs = with pkgs; [
      neovim coreutils git ripgrep fd gcc unzip curl
    ];

    text = ''
      export NVIM_APPNAME=isenguard
      config_home="''${XDG_CONFIG_HOME:-$HOME/.config}"
      target="$config_home/isenguard"

      # First launch copies editable configuration to the persistent home.
      # Subsequent launches never overwrite user changes.
      if [ ! -e "$target" ]; then
        mkdir -p -- "$target"
        cp -R -- ${isenguardSource}/. "$target/"
        chmod -R u+w -- "$target"
      fi

      exec nvim "$@"
    '';
  };
in
{
  environment.systemPackages = [ isenguard ];
}
