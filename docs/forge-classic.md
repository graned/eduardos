# Forge Classic — visual design milestone (PR #12)

Forge Classic is the signature **Obsidian Forge** preset. It is deliberately
warm, cinematic and industrial without introducing compositor blur,
animated wallpapers, extra agents or new runtime widget frameworks.

## Visual identity

- **Wallpaper**: generated 1920×1080 cinematic volcanic landscape (`themes/forge-classic/wallpaper.jpg`), featuring an obsidian mountain, glowing lava river, atmospheric smoke and the eduardOS emblem. The previous vector concept is retained as an inactive design reference (`wallpaper.svg`).
- **Waybar**: a dedicated Classic layout with a static eduardOS brand mark,
  styled workspace pills, grouped command-deck modules, warm clock focus
  and responsive spacing.
- **Ghostty**: warm high-contrast ANSI palette, softly contrasted black, more generous
  internal spacing and JetBrains Mono Nerd Font.
- **Fuzzel**: a compact searchable command palette, deliberate spacing, warm
  selection colors and a stronger border.
- **Mako**: compact industrial notification treatment.
- **Hyprland**: small refinements to gaps, rounding and focused borders,
  with the static `swaybg` wallpaper on this theme only.

## Lightweight implementation

The actual wallpaper is a bundled high-quality JPEG at **1920×1080**.
NixOS installs it directly at
`/etc/xdg/eduardos/forge-classic-wallpaper.jpg` and the existing
`swaybg` process displays it. There is **no SVG rasterization step,
runtime image conversion, animated wallpaper or compositor blur**.

We switched from `hyprpaper` after it crashed with SIGSEGV in the
software-rendered QEMU test; CI requires `swaybg` to remain running.
Personal Home Manager overrides remain possible.

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

## Developer shell and translucent Ghostty

eduardOS now installs **Zsh with Oh My Zsh** by default for new
accounts. Its bundled `eduardos-catppuccin` prompt uses the Catppuccin
Mocha palette (Peach, Mauve, Blue, Teal and Green) and the built-in
Oh My Zsh Git plugin. This configuration lives in
`nix/modules/development/shell.nix` and
`themes/shell/eduardos-catppuccin.zsh-theme`, without a shell startup
download or remote installation script. Users may override their own
shell preferences.

Forge Classic's Ghostty uses Catppuccin Mocha foreground and ANSI colors,
with `background-opacity = 0.88` so the volcanic wallpaper remains
subtly visible behind text. Ghostty and Hyprland handle compositor
blending; no blur daemon is installed. The distinct Neon and Brutalist
terminal configurations are not restyled in this PR.

The QEMU boot check validates the Zsh login shell, the Oh My Zsh theme
loaded in an interactive shell and the Ghostty opacity setting. The
same functional desktop and screenshot tests remain enabled.
