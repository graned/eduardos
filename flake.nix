{
  description = "eduardOS — Forged in Chaos: Obsidian Forge desktop";

  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-26.05/nixexprs.tar.zst";
  inputs.home-manager = {
    url = "github:nix-community/home-manager/release-26.05";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, home-manager }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      desktopModules = [
        ./nix/modules/core.nix
        ./nix/modules/desktop/hyprland.nix
        ./nix/modules/desktop/obsidian-forge.nix
        ./nix/modules/development/shell.nix
        ./nix/modules/development/opencode.nix
        ./nix/modules/development/isenguard.nix
      ];
      vmModules = desktopModules ++ [
        home-manager.nixosModules.home-manager
        ./hosts/virtual-machine/user.nix
      ];
    in
    {
      nixosConfigurations.eduardos-vm = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = vmModules ++ [
          ./hosts/virtual-machine/default.nix
        ];
      };

      packages.${system}.vm =
        self.nixosConfigurations.eduardos-vm.config.system.build.vm;

      checks.${system} = {
        # Evaluate and build the generated assets of every supported preset.
        # This catches invalid choices or broken recoloring without booting
        # three complete VMs.
        theme-presets =
          let
            themeStyles = name:
              (nixpkgs.lib.nixosSystem {
                inherit system;
                modules = vmModules ++ [
                  { eduardos.theme = name; system.stateVersion = "26.05"; }
                ];
              }).config.environment.etc."xdg/waybar/style.css".source;
          in pkgs.runCommand "eduardos-theme-presets" {
            classic = themeStyles "forge-classic";
            neon = themeStyles "forge-neon";
            brutalist = themeStyles "forge-brutalist";
          } ''
            grep -Fq '#f18a4e' "$classic"
            grep -Fq '#19c6bf' "$neon"
            grep -Fq '#ff8a45' "$brutalist"
            touch "$out"
          '';
        hyprland-session = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
        };
        theme-preview-classic = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
          theme = "forge-classic";
          preview = true;
        };
        theme-preview-neon = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
          theme = "forge-neon";
          preview = true;
        };
        theme-preview-brutalist = import ./nix/tests/hyprland-session.nix {
          inherit pkgs;
          modules = vmModules;
          theme = "forge-brutalist";
          preview = true;
        };

        boot = pkgs.testers.runNixOSTest {
        name = "eduardos-boot";
        nodes.machine = { ... }: {
          imports = vmModules;
          networking.hostName = "eduardos-test";
          system.stateVersion = "26.05";
        };
        testScript = ''
          machine.start()
          machine.wait_for_unit("multi-user.target")
          machine.succeed("uname -s | grep Linux")
          machine.succeed("systemctl is-active NetworkManager.service")
          machine.succeed("test -x /run/current-system/sw/bin/Hyprland")
          machine.succeed("test -x /run/current-system/sw/bin/brave")
          machine.succeed("test -x /run/current-system/sw/bin/zsh")
          machine.succeed("getent passwd forge | grep -q '/zsh$'")
          machine.succeed(
            "runuser -u forge -- zsh -ic 'print -r -- $ZSH_THEME' "
            "| grep -Fxq eduardos-catppuccin"
          )
          machine.succeed("getent passwd forge | grep -q '/zsh
          machine.succeed("test \"$(cat /etc/xdg/eduardos/theme)\" = forge-classic")
          machine.succeed("grep -Fq brave-browser.desktop /etc/xdg/mimeapps.list")
          machine.succeed("test -x /run/current-system/sw/bin/mpv")
          machine.succeed("opencode --version")
          # Home Manager must actually activate inside the guest.
          machine.wait_until_succeeds("test -f /home/forge/.config/eduardos/managed-by-home-manager")
          machine.succeed("grep -Fq 'profile: forge-vm' /home/forge/.config/eduardos/managed-by-home-manager")
          machine.succeed("env HOME=/tmp/edos-isenguard XDG_CONFIG_HOME=/tmp/edos-isenguard/config isenguard --version")
          machine.succeed("test -f /tmp/edos-isenguard/config/isenguard/init.lua")
          # Verify the actual desktop configuration lands in the booted guest.
          machine.succeed("test -r /etc/xdg/hypr/hyprland.conf")
          machine.succeed("grep -Fq 'exec-once = swaybg' /etc/xdg/hypr/hyprland.conf")
          machine.succeed("test -r /etc/xdg/eduardos/forge-classic-wallpaper.jpg")
          machine.succeed("test -s /etc/xdg/eduardos/forge-classic-wallpaper.jpg")
          machine.succeed("grep -Fq 'exec-once = waybar' /etc/xdg/hypr/hyprland.conf")
          machine.succeed("test -r /etc/xdg/waybar/config.jsonc")
          machine.succeed("test -r /etc/xdg/waybar/style.css")
          machine.succeed("test -r /etc/xdg/ghostty/config")
          machine.succeed("grep -Fqx 'background-opacity = 0.88' /etc/xdg/ghostty/config")
          machine.succeed("grep -Fqx 'background = #1e1e2e' /etc/xdg/ghostty/config")
          machine.succeed("test -r /etc/xdg/fuzzel/fuzzel.ini")
          machine.succeed("test -r /etc/xdg/mako/config")
        '';
      };
      };
    };
}
