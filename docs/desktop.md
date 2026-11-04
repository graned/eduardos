# eduardOS desktop — Obsidian Forge (v0.2 prototype)

Obsidian Forge is the first default visual identity for eduardOS.
It uses dark iron surfaces, molten orange accents, and accessible light text.

## Default interactions

| Shortcut | Action |
| --- | --- |
| Super + Enter | Open Ghostty |
| Super + D | Application launcher (Fuzzel) |
| Super + Q | Close active window |
| Super + F | Toggle fullscreen |
| Super + Space | Toggle floating window |
| Super + 1/2/3 | Switch workspace |
| Super + Shift + 1/2/3 | Move window to workspace |
| Super + Shift + E | Exit Hyprland |
| Super + left/right drag | Move / resize window |

## Configuration design

All base files are deployed to `/etc/xdg` rather than a user's home.
This allows a future Home Manager module to override any theme choice
without modifying the OS module or relying on hand-built symlinks.

The palette is deliberately conservative for daily usage:
- Obsidian: `#0b0d12`
- Iron: `#1b202b`
- Ember: `#e56b35`
- Warm ember: `#ffb366`
- Signal teal: `#40c9b6`
- Bone: `#e7e3dd`

This milestone does **not** verify Hyprland renders correctly inside QEMU.
The CI boot test checks that theme configuration is deployed and that
services and packages are available. An accelerated graphical test,
screenshots, and real hardware testing are separate acceptance criteria.

The default keyboard layout is US for the VM prototype and will become
configurable before an installable eduardOS release.
