# Forge Brutalist — Monumental basalt

**Forge Brutalist** is the third official eduardOS visual preset: sharp,
minimal industrial geometry inspired by Mesoamerican stone architecture,
with austere charcoal surfaces and restrained amber highlights.

## Visual identity

- **Wallpaper:** original, branded 1920×1080 artwork featuring a monumental
  basalt calendar relief, stepped ceremonial architecture, a storm-lit horizon,
  and the words **eduardOS — FORGED IN BRUTALISM**.
  The image is stored at `themes/forge-brutalist/wallpaper.jpg`.
- **Hyprland:** sharp 3px corner rounding, basalt window borders, warm amber
  focus outline. Existing keyboard shortcuts and startup behavior retained.
- **Waybar:** dedicated angular command deck with small branding panel,
  workspace indicators, clock and compact system statistics.
- **Ghostty:** dark graphite, coordinated amber/stone terminal colors,
  `background-opacity = 0.89`, JetBrains Mono Nerd Font.
- **Fuzzel and Mako:** square-ish notification and launcher frames,
  angular amber outlines and high-contrast typography.

## Performance

The full-resolution wallpaper is a static JPEG drawn using `swaybg`.
No animated compositor backgrounds, blur plugins, new polling daemons
or shell-time scripts are introduced. The original Oh My Zsh experience
remains the same across themes.

Forge Classic and Forge Neon assets remain unchanged.

## Graphical review

The NixOS graphical test boots each theme in QEMU and requires Hyprland,
Ghostty, Mako, Waybar, actual keyboard input, and the live wallpaper
process where applicable. It captures these Brutalist screenshots:

- `forge-brutalist-wallpaper.png` — empty workspace showing the original image
- `forge-brutalist-desktop.png` — single floating Ghostty with Waybar
- `forge-brutalist-launcher.png` — Fuzzel showing a `brave` query

Download them with the others from the GitHub Actions
`eduardos-theme-previews` artifact after CI succeeds. The workflow
requires **nine screenshots**, including Classic and Neon.

A passing build does not constitute visual design approval; review
the images before merging PR #14.
