{ modulesPath, pkgs, lib, ... }:
let
  # SVG text requires an explicit fontconfig file inside isolated Nix builders.
  eclipseFonts = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
in
{
  # The upstream NixOS installer ISO supplies initrd, ISO/EFI boot support,
  # squashfs root and a writable overlay. Do not import the Disko lab profile.
  imports = [
    (modulesPath + "/installer/cd-dvd/installation-cd-minimal.nix")
  ];

  networking.hostName = "eduardos-live";

  # Keep upstream NixOS ISO safety/compatibility but replace its visible
  # boot branding on UEFI GRUB and BIOS Syslinux.
  system.nixos.distroName = "eduardOS";
  isoImage.appendToMenuLabel = " — Forge Eclipse Live";
  isoImage.configurationName = "Forged in Neon";
  isoImage.syslinuxTheme = ''
    MENU TITLE eduardOS - Forged in Neon
    MENU RESOLUTION 800 600
    MENU CLEAR
    MENU ROWS 7
    MENU COLOR SCREEN 37;40 #ff0c090d #ff0c090d none
    MENU COLOR BORDER 30;40 #ff0c090d #ff0c090d none
    MENU COLOR TITLE 1;31;40 #ffd43a45 #ff0c090d none
    MENU COLOR SEL 7;37;40 #ffeee3dd #ff70202b std
    MENU COLOR UNSEL 37;40 #ffeee3dd #ff0c090d none
  '';

  # Generate RGB PNGs at image-build time; no expensive runtime effect.
  isoImage.splashImage = pkgs.runCommand "edos-bios-boot-image.png" {
    nativeBuildInputs = [ pkgs.librsvg ];
  } ''
    export FONTCONFIG_FILE="${eclipseFonts}"
    export XDG_CACHE_HOME="$TMPDIR/edos-fontconfig-cache"
    mkdir -p "$XDG_CACHE_HOME"
    rsvg-convert -w 800 -h 600 ${../../themes/forge-eclipse/wallpaper.svg} -o "$out"
  '';
  isoImage.efiSplashImage = pkgs.runCommand "edos-efi-boot-image.png" {
    nativeBuildInputs = [ pkgs.librsvg ];
  } ''
    export FONTCONFIG_FILE="${eclipseFonts}"
    export XDG_CACHE_HOME="$TMPDIR/edos-fontconfig-cache"
    mkdir -p "$XDG_CACHE_HOME"
    rsvg-convert -w 1280 -h 720 ${../../themes/forge-eclipse/wallpaper.svg} -o "$out"
  '';
  isoImage.grubTheme = pkgs.runCommand "edos-grub-boot-theme" {
    nativeBuildInputs = [ pkgs.librsvg pkgs.grub2 ];
  } ''
    mkdir -p "$out"
    export FONTCONFIG_FILE="${eclipseFonts}"
    export XDG_CACHE_HOME="$TMPDIR/edos-fontconfig-cache"
    mkdir -p "$XDG_CACHE_HOME"
    rsvg-convert -w 1280 -h 720 ${../../themes/forge-eclipse/wallpaper.svg} -o "$out/background.png"
    grub-mkfont -s 18 -o "$out/mono.pf2" ${pkgs.dejavu_fonts}/share/fonts/truetype/DejaVuSansMono.ttf
    cat > "$out/theme.txt" <<'EOF'
    title-text: "eduardOS  /  FORGED IN NEON"
    title-font: "DejaVu Sans Mono Regular 18"
    title-color: "#eee3dd"
    desktop-image: "background.png"
    desktop-color: "#0c090d"
    + boot_menu {
      left = 8%
      top = 43%
      width = 55%
      height = 36%
      item_font = "DejaVu Sans Mono Regular 18"
      item_color = "#eee3dd"
      selected_item_color = "#ffffff"
      selected_item_pixmap_style = ""
      item_height = 32
      item_spacing = 7
    }
    + label {
      left = 8%
      top = 86%
      width = 75%
      height = 28
      text = "FORGE ECLIPSE  -  LIVE PREVIEW / NO AUTOMATIC DISK CHANGES"
      color = "#d43a45"
      font = "DejaVu Sans Mono Regular 18"
    }
    EOF
  '';
  system.stateVersion = "26.05";

  # The live ISO previews the default dark-fantasy Forge Eclipse identity.
  eduardos.theme = "forge-eclipse";

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

  # The live preview opens Forge on first graphical login, not the default
  # NixOS text installer. This runs as the unprivileged 'forge' user and
  # exposes ONLY the read-only preview; no disk-writing endpoint exists.
  # Closing the browser leaves the live desktop usable.
  environment.etc."xdg/hypr/hyprland.conf".source = lib.mkForce (
    pkgs.writeText "eduardos-live-hyprland.conf" (
      builtins.readFile ../../themes/forge-eclipse/hyprland.conf
      + "\nexec-once = sh -c 'sleep 3; forge-installer-gui'\n"
    )
  );

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
        printf '%s\n' 'EDOS_LIVE_BOOT_OK=alpha-0.1-preview' > /dev/ttyS0
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
