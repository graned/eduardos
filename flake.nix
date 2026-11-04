{
  description = "eduardOS — Forged in Chaos: NixOS VM foundation";

  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-26.05/nixexprs.tar.zst";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
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
    };
}
