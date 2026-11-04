{ pkgs, modules, theme ? "forge-classic", preview ? false }:

pkgs.testers.runNixOSTest {
  name = "eduardos-hyprland-${theme}${if preview then "-preview" else ""}";
  nodes.machine = { ... }: {
    imports = modules;
    networking.hostName = "eduardos-graphical-test";
    system.stateVersion = "26.05";
    eduardos.theme = theme;

    # A software-rendered QEMU smoke test, not a GPU performance test.
    environment.variables.LIBGL_ALWAYS_SOFTWARE = "1";

    # NixOS test guests are console-first and need an explicit virtual
    # graphics device for Aquamarine to initialize a DRM backend.
    # This remains a software-rendered, non-accelerated smoke test.
    virtualisation.qemu.options = [ "-device virtio-vga" ];
    hardware.graphics.enable = true;

    # Give the test account a seat manager able to broker DRM/input fds.
    # Never use chmod 666 on /dev/dri or launch Hyprland as root.
    services.seatd.enable = true;
    users.users.forge.extraGroups = [ "seat" "video" "render" ];
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

    # The nested Weston test failed to supply an allocator despite
    # advertising the necessary protocols. Test native DRM via seatd.
    machine.wait_for_unit("seatd.service")
    machine.wait_until_succeeds("test -S /run/seatd.sock", timeout=30)
    machine.succeed("id forge")
    machine.succeed("ls -l /run/seatd.sock /dev/dri/card0")

    # Start Hyprland using the SAME configuration we ship. Preserve the
    # version in pinned Nixpkgs; don't override upstream packages.
    machine.succeed(
        "systemd-run --unit=edos-hyprland-smoke --collect "
        "--property=User=forge "
        "--property=WorkingDirectory=/home/forge "
        "--setenv=HOME=/home/forge "
        f"--setenv=XDG_RUNTIME_DIR={runtime} "
        "--setenv=LIBGL_ALWAYS_SOFTWARE=1 "
        "--setenv=LIBSEAT_BACKEND=seatd "
        "--setenv=AQ_NO_KMS_REQUIREMENT=1 "
        "--setenv=HYPRLAND_NO_RT=1 "
        "--setenv=AQ_TRACE=1 "
        "--setenv=HYPRLAND_TRACE=1 "
        "--setenv=PATH=/run/current-system/sw/bin:/run/wrappers/bin "
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
        # Nix binaries may use .waybar-wrapped/.mako-wrapped process names.
        # Match their exact command lines as the forge user instead.
        machine.wait_until_succeeds(
            "pgrep -u forge -f '^waybar$' >/dev/null", timeout=30
        )
        machine.wait_until_succeeds(
            "pgrep -u forge -f '^mako$' >/dev/null", timeout=30
        )
        machine.succeed("test -x /run/current-system/sw/bin/ghostty")
        machine.succeed("grep -Fxq '${theme}' /etc/xdg/eduardos/theme")

        # Query the compositor itself; a Ghostty process alone does not
        # prove that a Wayland surface was mapped successfully.
        # The instance signature is created by Hyprland at runtime.
        signature = machine.succeed(
            f"find {runtime}/hypr -mindepth 1 -maxdepth 1 "
            "-type d -printf '%f\\n' | head -n 1"
        ).strip()
        assert signature, "Hyprland did not create an instance directory"
        session_env = (
            f"XDG_RUNTIME_DIR={runtime} "
            f"HYPRLAND_INSTANCE_SIGNATURE={signature} "
            "PATH=/run/current-system/sw/bin:/run/wrappers/bin"
        )
        def hyprctl(command):
            return machine.succeed(
                f"runuser -u forge -- env {session_env} "
                f"/run/current-system/sw/bin/hyprctl {command}"
            )
        # Avoid silently passing if no output is configured.
        assert "Monitor " in hyprctl("monitors"), (
            "Hyprland started, but no usable monitor was reported"
        )
        hyprctl("dispatch exec ghostty")
        machine.wait_until_succeeds(
            f"runuser -u forge -- env {session_env} "
            "/run/current-system/sw/bin/hyprctl clients "
            "| grep -iq ghostty",
            timeout=45
        )
        # Capture a baseline of the mapped desktop. Screenshot files
        # become outputs of the successful NixOS test derivation.
        machine.screenshot("obsidian-forge-ghostty-before.png")
        if ${if preview then "True" else "False"}:
            machine.screenshot("${theme}-desktop.png")
            if ${if theme == "forge-classic" then "True" else "False"}:
                # A clean view exposes the wallpaper otherwise hidden
                # behind maximized/tiled terminal windows.
                machine.wait_until_succeeds(
                    "pgrep -u forge -f '^hyprpaper$' >/dev/null",
                    timeout=30
                )
                machine.succeed("test -r /etc/xdg/hypr/hyprpaper.conf")
                hyprctl("dispatch workspace 2")
                machine.wait_until_succeeds(
                    f"runuser -u forge -- env {session_env} "
                    "/run/current-system/sw/bin/hyprctl -j activeworkspace "
                    "| grep -Eq '\\\"id\\\":[[:space:]]*2'",
                    timeout=15
                )
                machine.screenshot("forge-classic-wallpaper.png")
                hyprctl("dispatch workspace 1")

        # Exercise the *actual virtual keyboard* through QEMU and our
        # shipped Super+Return shortcut, rather than hyprctl dispatch.
        import json
        import time
        def ghostty_windows():
            clients = json.loads(hyprctl("-j clients"))
            return sum(
                "ghostty" in str(c.get("class", "")).lower()
                or "ghostty" in str(c.get("initialClass", "")).lower()
                for c in clients
            )

        baseline = ghostty_windows()
        assert baseline >= 1, "No mapped Ghostty client before keyboard test"
        machine.send_key("meta_l-ret")
        for attempt in range(45):
            if ghostty_windows() > baseline:
                break
            time.sleep(1)
        else:
            raise AssertionError(
                "Super+Return did not map an additional Ghostty window"
            )
        machine.screenshot("obsidian-forge-ghostty-after-shortcut.png")
        if ${if preview then "True" else "False"}:
            machine.send_key("meta_l-d")
            machine.wait_until_succeeds(
                "pgrep -u forge -f '^fuzzel$' >/dev/null",
                timeout=30
            )
            machine.screenshot("${theme}-launcher.png")
        machine.succeed("systemctl is-active edos-hyprland-smoke.service")
    except Exception:
        print(machine.succeed(
            "journalctl -u edos-hyprland-smoke.service --no-pager -n 120 || true"
        ))
        print(machine.succeed(
            "journalctl -u seatd.service --no-pager -n 120 || true"
        ))
        print(machine.succeed("ps -u forge -o pid,comm,args || true"))
        print(machine.succeed("find /run/user/$(id -u forge)/hypr -maxdepth 2 -ls || true"))
        print(machine.succeed(
            "ls -la /dev/dri /run/user/$(id -u forge) || true"
        ))
        print(machine.succeed(
            "find /home/forge/.cache/hyprland -maxdepth 1 "
            "-name 'hyprlandCrashReport*' -type f -exec cat {} + "
            "2>/dev/null || true"
        ))
        print(machine.succeed(
            "find /run/user/$(id -u forge)/hypr "
            "-name 'hyprland.log' -type f -exec cat {} + "
            "2>/dev/null || true"
        ))
        raise
  '';
}
