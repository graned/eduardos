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

A passing result establishes *DRM compositor startup and a mapped Ghostty
window in QEMU*, not complete desktop acceptance. It does not prove
correct visual rendering, GPU acceleration, browser usability, audio,
keyboard/mouse behavior, display hotplug, or physical hardware compatibility.

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
