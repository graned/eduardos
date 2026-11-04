# Forge Classic — visual design milestone (PR #12)

Forge Classic is the signature **Obsidian Forge** preset. It is deliberately
warm, cinematic and industrial without introducing compositor blur,
animated wallpapers, extra agents or new runtime widget frameworks.

## Visual identity

- **Wallpaper**: original vector landscape (`themes/forge-classic/wallpaper.svg`)
  with layered obsidian ridges, a winding molten river, atmospheric furnace
  glow, textured terrain and a restrained forged-anvil eduardOS mark.
- **Waybar**: a dedicated Classic layout with a static eduardOS brand mark,
  styled workspace pills, grouped command-deck modules, warm clock focus
  and responsive spacing.
- **Ghostty**: warm high-contrast ANSI palette, softly contrasted black, more generous
  internal spacing and JetBrains Mono Nerd Font.
- **Fuzzel**: a compact searchable command palette, deliberate spacing, warm
  selection colors and a stronger border.
- **Mako**: compact industrial notification treatment.
- **Hyprland**: small refinements to gaps, rounding and focused borders,
  with a static hyprpaper background on this theme only.

## Lightweight implementation

The wallpaper is stored as editable SVG source, rendered once during the
**Nix build** into a 1920×1080 PNG using `librsvg`; there is no runtime
conversion process. The lightweight `swaybg` wallpaper process is installed and started
only with the Classic preset. The previously used `hyprpaper` crashed
with SIGSEGV in the software-rendered QEMU test, leaving a blank desktop;
CI now checks that swaybg remains alive after startup. No animations or
blur are added, and the user's own Home Manager configuration continues
to override system fallbacks.

Forge Neon and Forge Brutalist still use their original palettes and
configs. They will get independent design work in later PRs.

## How to review the actual result

GitHub Actions runs the usual boot and graphical assertions plus all
three preset previews. The successful run uploads the
`eduardos-theme-previews` artifact. In addition to six existing UI
screenshots, the `forge-classic-wallpaper.png` is captured from
an **empty Hyprland workspace**. The `forge-classic-desktop.png` now
shows a **single 900×540 floating Ghostty window** for a useful hero view,
and `forge-classic-launcher.png` uses the real Fuzzel launcher with a
`brave` search query, instead of an empty prompt.

The independent keyboard test still proves that Super+Return opens
a second mapped Ghostty window. These preview-only layout changes
do not modify users' normal tiling behavior.

Evaluate the PNGs before merging. A green build proves startup and
screenshot capture, not visual quality.

## Remaining scope

No first-boot installer, login screen redesign, Neon/Brutalist artwork,
audio or visual pixel-diff thresholds are included here.
