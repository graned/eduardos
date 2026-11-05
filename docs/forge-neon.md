# Forge Neon — Tlaloc: Forged in Neon

The second complete eduardOS visual theme is a **rain-soaked cyber-Aztec
temple** inspired by Tlaloc, the rain deity. This is an original fantasy
design rather than a historical reconstruction.

## Visual identity

- **Wallpaper**: original approved, branded **1920×1080 JPEG** at
  `themes/forge-neon/wallpaper.jpg`; a monumental rain-god stone mask
  and flowing turquoise water stand beside a lightning storm, rainy
  obsidian terraces, amber temple details, and the words **eduardOS —
  FORGED IN NEON**. This image is packaged in the Git repository; no
  runtime download or generated substitute is used.
- **Waybar**: theme-specific compact command deck, eduardOS/NEON brand
  chip, teal active workspace and clock, amber highlights.
- **Ghostty**: 88%-opaque, dark-blue terminal with cyan, mint, rain-blue
  and amber ANSI colors. The wallpaper remains subtly visible.
- **Fuzzel**: compact turquoise launcher with a warm highlighted match.
- **Mako**: coordinated dark teal notifications.
- **Hyprland**: teal focus borders, small gaps, no blur; starts lightweight
  `swaybg` to display the bundled image.

This remains a **static wallpaper by default**. Animated rain would
require a separate optional wallpaper engine and performance evaluation,
and is deliberately out of scope for PR #13.

## Theme selection

Set in your host's NixOS module:

```nix
eduardos.theme = "forge-neon";
```

No new shell configuration, launch keybinds, window-management behavior,
browser settings or compositor package versions are introduced. Forge
Classic and Brutalist retain their own existing files.

## Visual acceptance from real QEMU

The CI theme preview tests run a real Hyprland compositor and capture:

- `forge-neon-wallpaper.png`: empty workspace to inspect branding,
  Tlaloc architecture and storm lighting;
- `forge-neon-desktop.png`: 900×540 floating Ghostty over wallpaper,
  with the new Neon Waybar;
- `forge-neon-launcher.png`: centered Fuzzel on an uncluttered workspace
  with `brave` typed, so selection styling is visible.

The functional Super+Return, Waybar/Mako startup, Ghostty mapping and
other desktop checks remain mandatory. Successful screenshots appear in
the `eduardos-theme-previews` GitHub Actions artifact.

**Review the actual screenshots before merging.** Green CI confirms
packages, config, startup and interactions, not artistic quality.
