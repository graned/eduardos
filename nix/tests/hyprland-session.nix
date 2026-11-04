{ pkgs, modules }:

pkgs.testers.runNixOSTest {
  name = "eduardos-hyprland-session";
  nodes.machine = { ... }: {
    imports = modules;
    networking.hostName = "eduardos-graphical-test";
    system.stateVersion = "26.05";

    # A software-rendered QEMU smoke test, not a GPU performance test.
    environment.variables.LIBGL_ALWAYS_SOFTWARE = "1";
  };

  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_until_succeeds(
        "test -f /home/forge/.config/eduardos/managed-by-home-manager"
    )

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

    # Fail if Hyprland exits early, and surface the journal for diagnosis.
    machine.wait_until_succeeds(
        "test -S /run/user/$(id -u forge)/wayland-1 "
        "|| test -S /run/user/$(id -u forge)/wayland-0",
        timeout=90
    )
    machine.succeed("systemctl is-active edos-hyprland-smoke.service")
    machine.succeed(
        "journalctl -u edos-hyprland-smoke.service --no-pager -n 50"
    )
  '';
}
