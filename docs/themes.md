# Obsidian Forge appearance presets

eduardOS has three official lightweight appearance presets:

| Preset | Default focus color | Character |
| --- | --- | --- |
| `forge-classic` | Ember orange `#e56b35` | Warm industrial forge (default) |
| `forge-neon` | Signal teal `#19c6bf` | Futuristic cyber-forge |
| `forge-brutalist` | Sharp orange `#ff8a45` | Restrained high-contrast minimal |

All presets share the **same** Hyprland shortcuts, developer packages,
and core desktop behavior. Forge Classic and Forge Neon now have
independent artwork, Waybar layouts, Ghostty palettes, launcher styling
and static wallpapers. Forge Brutalist still uses the shared palette
foundation. Each of the first two themes uses the same lightweight
`swaybg` engine, not video playback or a runtime CSS service.

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

Forge Classic and Forge Neon each have an original branded high-definition
wallpaper packaged directly in the repository. See
[`forge-classic.md`](forge-classic.md) and [`forge-neon.md`](forge-neon.md)
for screenshots and visual details. Forge Brutalist is scheduled next.

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
captures three actual VM display screenshots for each theme:

| Theme | Wallpaper | Desktop | Launcher |
| --- | --- | --- | --- |
| Classic | `forge-classic-wallpaper.png` | `forge-classic-desktop.png` | `forge-classic-launcher.png` |
| Neon | `forge-neon-wallpaper.png` | `forge-neon-desktop.png` | `forge-neon-launcher.png` |
| Brutalist | `forge-brutalist-wallpaper.png` | `forge-brutalist-desktop.png` | `forge-brutalist-launcher.png` |

Download the screenshots from **Actions → successful workflow run →
Artifacts → `eduardos-theme-previews`**. There are now additional
empty-workspace wallpaper screenshots for Classic and Neon, for eight
screenshots total. Artifacts are kept for 14 days.
If a preview test fails, files produced by earlier themes may still be
uploaded; the VM logs provide the startup failure details.

The preview images reflect the **current shipped UI**, including the
branded wallpapers for Classic and Neon. Screenshot capture is automatic;
pixel-diff comparison is deliberately not a pass/fail criterion yet.

To build an individual theme preview on an x86_64 Linux KVM host:

```sh
nix build .#checks.x86_64-linux.theme-preview-neon -L
```
