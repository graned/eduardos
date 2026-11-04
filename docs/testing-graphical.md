# Graphical session smoke test

This integration test starts the **stable, Nixpkgs-pinned Hyprland**
version configured for eduardOS, with the same Obsidian Forge
`hyprland.conf` that is deployed to the VM.

Run on an x86_64 Linux host with Nix and KVM:

```sh
nix build .#checks.x86_64-linux.hyprland-session -L
```

The test boots NixOS under QEMU with a virtual `virtio-vga` GPU,
starts pinned Hyprland through `seatd` as the unprivileged `forge` user,
and requires a live Wayland socket and compositor service.

It also verifies that Waybar and Mako really start from the shipped
`exec-once` configuration, then launches Ghostty via Hyprland's IPC.
It **requires Hyprland to report a mapped Ghostty client window**, not
merely a running Ghostty process. The compositor must remain active.
This is not a substitute for a login-manager test or physical hardware
testing.

The test also captures a screenshot of the running compositor with Ghostty,
sends `Super+Return` through QEMU's virtual keyboard, and requires Hyprland
to report **another** mapped Ghostty window. A second screenshot is taken
after the shortcut. This checks a real keyboard path rather than just an IPC
command; no OCR or pixel comparison is used to decide pass/fail.

On successful GitHub Actions runs, both PNGs are uploaded as the
`obsidian-forge-desktop-screenshots` artifact (retained 14 days).
On failed Nix builds these images may not be available, so consult
the VM driver and Hyprland logs; screenshot uploads are best-effort.

A passing result establishes *DRM compositor startup and a mapped Ghostty
window in QEMU*, not complete desktop acceptance. It does not prove
correct visual rendering, GPU acceleration, browser usability, audio,
mouse behavior, sustained text input, display hotplug, or physical hardware compatibility.

## Version and migration policy

- **Stay on the stable NixOS 26.05 package set** for this milestone.
- Do not add an independently moving Hyprland flake.
- Keep `hyprland.conf` while it is supported by the shipped package.
- Before upgrading to a release requiring Lua, create a separately
  tested eduardOS migration path with backups, dry-run/diff, explicit
  consent and rollback support.
- Never silently rewrite or discard a user's customized configuration.

If CI fails because this guest does not expose a suitable renderer or
seat, record the limitation and adjust the test harness rather than
disabling the assertion or calling it a success.
