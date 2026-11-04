# Obsidian Forge appearance presets

eduardOS has three official lightweight appearance presets:

| Preset | Default focus color | Character |
| --- | --- | --- |
| `forge-classic` | Ember orange `#e56b35` | Warm industrial forge (default) |
| `forge-neon` | Signal teal `#19c6bf` | Futuristic cyber-forge |
| `forge-brutalist` | Sharp orange `#ff8a45` | Restrained high-contrast minimal |

All presets use the **same** Hyprland key bindings, startup commands,
Waybar modules, fonts, packages and performance settings. The NixOS
module recolors the same shared config files at build time, so changing
presets does not add a runtime CSS engine, daemon or separate compositor.

## Choose a preset

Set the following NixOS option in your host configuration:

```nix
{
  eduardos.theme = "forge-neon";
}
```

Allowed values: `forge-classic`, `forge-neon`, `forge-brutalist`.

If omitted, the default is `forge-classic`. Apply the change with the
usual `nixos-rebuild switch --flake ...` for your installed host. The
disposable QEMU VM is a prototype, not an installable disk image.

The selected preset is recorded at `/etc/xdg/eduardos/theme`. The
generated fallback configs live in `/etc/xdg/`; per-user Home Manager
configuration can still override those values. Switching themes must
never overwrite custom files in a user's home directory.

## Initial setup and visual assets — upcoming work

This PR establishes the selectable *NixOS option* and palette variants.
**A first-boot installer/theme chooser does not exist yet.** When the
installer is implemented, it should offer all three previews, write the
selected option into the generated host configuration, and explain that
users can switch themes later. That should happen before the first user
session, not by mutating files in `~/.config` behind the user's back.

This is a color-preset foundation. The distinct custom artwork,
wallpapers and richer visual styling shown in concept images will be
produced and reviewed in a separate design/implementation PR.

## Default web browser

eduardOS installs **Brave**, not Firefox, in the default desktop package
set. The system sets `BROWSER=brave` and XDG MIME associations for HTML
and HTTP(S) links to `brave-browser.desktop`. Users may override their
preferred browser through their own XDG MIME settings.

## Validation

```sh
nix build .#checks.x86_64-linux.theme-presets -L
nix build .#checks.x86_64-linux.boot -L
nix build .#checks.x86_64-linux.hyprland-session -L
```

The first check builds generated Waybar CSS for all three choices and
verifies each accent color. The others still require real NixOS boot
and Hyprland graphical-session behavior.

## Real desktop screenshots from CI

PRs also boot all three themes in separate QEMU guests, start Hyprland,
Waybar, Mako and Ghostty, verify that the Super+Return shortcut maps
another Ghostty window, and invoke Fuzzel through Super+D. The test
captures two actual VM display screenshots for each theme:

| Theme | Desktop | Launcher |
| --- | --- | --- |
| Classic | `forge-classic-desktop.png` | `forge-classic-launcher.png` |
| Neon | `forge-neon-desktop.png` | `forge-neon-launcher.png` |
| Brutalist | `forge-brutalist-desktop.png` | `forge-brutalist-launcher.png` |

Download all six from **Actions → successful workflow run →
Artifacts → `eduardos-theme-previews`**. Artifacts are kept for 14 days.
If a preview test fails, files produced by earlier themes may still be
uploaded; the VM logs provide the startup failure details.

The preview images reflect the **current shipped UI**, not the cinematic
concept art. Wallpaper artwork, theme-specific backgrounds and deeper
styling are still separate design work. Screenshot capture is automatic;
pixel-diff comparison is deliberately not a pass/fail criterion yet.

To build an individual theme preview on an x86_64 Linux KVM host:

```sh
nix build .#checks.x86_64-linux.theme-preview-neon -L
```
