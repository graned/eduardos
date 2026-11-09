{ modulesPath, pkgs, lib, ... }:

{
  # The upstream NixOS installer ISO supplies initrd, ISO/EFI boot support,
  # squashfs root and a writable overlay. Do not import the Disko lab profile.
  imports = [
    (modulesPath + "/installer/cd-dvd/installation-cd-minimal.nix")
  ];

  networking.hostName = "eduardos-live";
  system.stateVersion = "26.05";

  # The first image showcases the neon/Tlaloc look; switching presets comes later.
  eduardos.theme = "forge-neon";

  # The live session is disposable. No hardcoded target device or disk
  # provisioning happens during boot.
  users.users.forge = {
    isNormalUser = true;
    initialPassword = "forge";
    extraGroups = [ "wheel" "networkmanager" "video" "audio" ];
  };

  # The installer CD normally auto-logs into a console. Reserve tty1 for
  # the graphical greeter instead; keep remaining consoles usable.
  services.getty.autologinUser = lib.mkForce null;

  # Launch the actual Wayland desktop directly from greetd. A fallback
  # greeter remains available if the initial graphical session exits.
  services.greetd = {
    enable = true;
    settings = {
      initial_session = {
        command = "${pkgs.hyprland}/bin/Hyprland";
        user = "forge";
      };
      default_session = {
        command = "${pkgs.greetd.tuigreet}/bin/tuigreet --time --cmd ${pkgs.hyprland}/bin/Hyprland";
        user = "greeter";
      };
    };
  };

  # Diskless QEMU acceptance observes this over the emulated serial port.
  # This runs only in the disposable live ISO after multi-user.target starts.
  # It grants no installer authority and touches no storage devices.
  systemd.services.edos-live-boot-probe = {
    description = "eduardOS live preview boot acknowledgement (serial only)";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    serviceConfig.Type = "oneshot";
    script = ''
      if [ -c /dev/ttyS0 ]; then
        printf '%s\\n' 'EDOS_LIVE_BOOT_OK=alpha-0.1-preview' > /dev/ttyS0
      fi
    '';
  };

  hardware.graphics.enable = true;

  # Some desktop applications need these in a live, read-only-root environment.
  environment.systemPackages = with pkgs; [
    foot
    pciutils
    usbutils
  ];

  environment.etc."eduardos/live-release".text = ''
    eduardOS Alpha 0.1 — Forged in Neon
    Disposable live environment; no automatic partitioning or installation.
    Live account: forge
  '';

  # Live credentials are intentionally public and never carried into an
  # installed system. ISO only; not part of the production install modules.
  security.sudo.wheelNeedsPassword = lib.mkForce false;
}
