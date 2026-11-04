# Forge Classic — visual design milestone (PR #12)

Forge Classic is the signature **Obsidian Forge** preset. It is deliberately
warm, cinematic and industrial without introducing compositor blur,
animated wallpapers, extra agents or new runtime widget frameworks.

## Visual identity

- **Wallpaper**: original vector landscape (`themes/forge-classic/wallpaper.svg`)
  with volcanic mountain silhouettes, ember flow, geometric detail and
  a custom forged-anvil eduardOS mark.
- **Waybar**: styled workspace pills, compact command-deck modules,
  warmer focus state and improved typography.
- **Ghostty**: warm high-contrast ANSI palette, softer black, internal spacing.
- **Fuzzel**: deliberate prompt/search spacing, warmer selection, stronger border.
- **Mako**: compact industrial notification treatment.
- **Hyprland**: small refinements to gaps, rounding and focused borders,
  with a static hyprpaper background on this theme only.

## Lightweight implementation

The wallpaper is stored as editable SVG source, rendered once during the
**Nix build** into a 1920×1080 PNG using `librsvg`; there is no runtime
conversion process. Hyprpaper is already included in eduardOS's desktop
packages and is started only with the Classic preset. No animations or
blur are added, and the user's own Home Manager configuration continues
to override system fallbacks.

Forge Neon and Forge Brutalist still use their original palettes and
configs. They will get independent design work in later PRs.

## How to review the actual result

GitHub Actions runs the usual boot and graphical assertions plus all
three preset previews. The successful run uploads the
`eduardos-theme-previews` artifact. In addition to six existing UI
screenshots, the new `forge-classic-wallpaper.png` is captured from
an **empty Hyprland workspace** so the artwork is visible without a
terminal window hiding it.

Evaluate the PNGs before merging. A green build proves startup and
screenshot capture, not visual quality.

## Remaining scope

No first-boot installer, login screen redesign, Neon/Brutalist artwork,
audio or visual pixel-diff thresholds are included here.
