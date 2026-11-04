{ pkgs, modules }:

pkgs.testers.runNixOSTest {
  name = "eduardos-hyprland-session";
  nodes.machine = { ... }: {
    imports = modules;
    networking.hostName = "eduardos-graphical-test";
    system.stateVersion = "26.05";

    # A software-rendered QEMU smoke test, not a GPU performance test.
    environment.variables.LIBGL_ALWAYS_SOFTWARE = "1";

    # NixOS test guests are console-first and need an explicit virtual
    # graphics device for Aquamarine to initialize a DRM backend.
    # This remains a software-rendered, non-accelerated smoke test.
    virtualisation.qemu.options = [ "-device virtio-vga" ];
    hardware.graphics.enable = true;
    users.users.forge.extraGroups = [ "video" "render" ];
  };

  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_until_succeeds(
        "test -f /home/forge/.config/eduardos/managed-by-home-manager"
    )

    # Fail with an actionable message if the virtual DRM device is
    # absent, rather than timing out after Hyprland crashes.
    machine.wait_until_succeeds("test -e /dev/dri/card0", timeout=30)
    machine.succeed("ls -l /dev/dri")

    # Linger creates a normal logind user runtime directory.
    machine.succeed("loginctl enable-linger forge")
    machine.wait_until_succeeds("test -d /run/user/$(id -u forge)")

    uid = machine.succeed("id -u forge").strip()
    runtime = f"/run/user/{uid}"

    # Start Hyprland using the SAME configuration we ship. Preserve the
    # version in pinned Nixpkgs; don't override upstream packages.
    machine.succeed(
        "systemd-run --unit=edos-hyprland-smoke --collect "
        "--property=User=forge "
        "--property=WorkingDirectory=/home/forge "
        "--setenv=HOME=/home/forge "
        f"--setenv=XDG_RUNTIME_DIR={runtime} "
        "--setenv=LIBGL_ALWAYS_SOFTWARE=1 "
        "--setenv=AQ_NO_KMS_REQUIREMENT=1 "
        "--setenv=HYPRLAND_NO_RT=1 "
        "/run/current-system/sw/bin/Hyprland "
        "--config /etc/xdg/hypr/hyprland.conf"
    )

    # A socket and active compositor are both required.
    # On failure print the actual startup journal before raising.
    try:
        machine.wait_until_succeeds(
            "test -S /run/user/$(id -u forge)/wayland-1 "
            "|| test -S /run/user/$(id -u forge)/wayland-0",
            timeout=40
        )
        machine.succeed("systemctl is-active edos-hyprland-smoke.service")
    except Exception:
        print(machine.succeed(
            "journalctl -u edos-hyprland-smoke.service --no-pager -n 120 || true"
        ))
        print(machine.succeed(
            "ls -la /dev/dri /run/user/$(id -u forge) || true"
        ))
        raise
  '';
}
