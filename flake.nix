{
  description = "eduardOS — Forged in Chaos: NixOS VM foundation";

  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-26.05/nixexprs.tar.zst";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
    in
    {
      nixosConfigurations.eduardos-vm = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          ./nix/modules/core.nix
          ./nix/modules/desktop/hyprland.nix
          ./hosts/virtual-machine/default.nix
        ];
      };

      packages.${system}.vm =
        self.nixosConfigurations.eduardos-vm.config.system.build.vm;

      # This test actually boots a Linux guest under QEMU and asserts
      # systemd services and desktop packages are present.
      checks.${system}.boot = pkgs.testers.runNixOSTest {
        name = "eduardos-boot";
        nodes.machine = { ... }: {
          imports = [
            ./nix/modules/core.nix
            ./nix/modules/desktop/hyprland.nix
          ];
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
        '';
      };
    };
}
