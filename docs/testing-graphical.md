# Graphical session smoke test

This integration test starts the **stable, Nixpkgs-pinned Hyprland**
version configured for eduardOS, with the same Obsidian Forge
`hyprland.conf` that is deployed to the VM.

Run on an x86_64 Linux host with Nix and KVM:

```sh
nix build .#checks.x86_64-linux.hyprland-session -L
```

The test boots NixOS under QEMU with a virtual `virtio-vga` GPU and
starts the pinned Hyprland compositor directly using the `seatd` seat
manager under the non-root `forge` account. It verifies that `seatd` is
running and that the DRM device exists, then requires a Wayland socket
and an active Hyprland process. These checks do not substitute for a
real graphical login session or physical hardware testing.

A passing result establishes *DRM compositor startup in QEMU*, not a complete desktop
acceptance test. It does not prove GPU acceleration, browser rendering,
audio, input handling, display hotplug or real hardware compatibility.

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
