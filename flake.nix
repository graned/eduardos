{
  description = "eduardOS — Forged in Chaos: Obsidian Forge desktop";

  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-26.05/nixexprs.tar.zst";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      desktopModules = [
        ./nix/modules/core.nix
        ./nix/modules/desktop/hyprland.nix
        ./nix/modules/desktop/obsidian-forge.nix
        ./nix/modules/development/opencode.nix
      ];
    in
    {
      nixosConfigurations.eduardos-vm = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = desktopModules ++ [
          ./hosts/virtual-machine/default.nix
        ];
      };

      packages.${system}.vm =
        self.nixosConfigurations.eduardos-vm.config.system.build.vm;

      checks.${system}.boot = pkgs.testers.runNixOSTest {
        name = "eduardos-boot";
        nodes.machine = { ... }: {
          imports = desktopModules;
          networking.hostName = "eduardos-test";
          system.stateVersion = "26.05";
        };
        testScript = ''
          machine.start()
          machine.wait_for_unit("multi-user.target")
          machine.succeed("uname -s | grep Linux")
          machine.succeed("systemctl is-active NetworkManager.service")
          machine.succeed("test -x /run/current-system/sw/bin/Hyprland")
          machine.succeed("test -x /run/current-system/sw/bin/firefox")
          machine.succeed("test -x /run/current-system/sw/bin/mpv")
          machine.succeed("opencode --version")
          # Verify the actual desktop configuration lands in the booted guest.
          machine.succeed("test -r /etc/xdg/hypr/hyprland.conf")
          machine.succeed("grep -Fq 'exec-once = waybar' /etc/xdg/hypr/hyprland.conf")
          machine.succeed("test -r /etc/xdg/waybar/config.jsonc")
          machine.succeed("test -r /etc/xdg/waybar/style.css")
          machine.succeed("test -r /etc/xdg/ghostty/config")
          machine.succeed("test -r /etc/xdg/fuzzel/fuzzel.ini")
          machine.succeed("test -r /etc/xdg/mako/config")
        '';
      };
    };
}
