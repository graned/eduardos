# Forge Eclipse — dedicated artwork for wallpaper and installer

The Forge Eclipse desktop wallpaper and the unprivileged Forge installer
preview now have **different approved artwork** in the same dark-fantasy
visual language. The installer uses the separate *Ruins Beneath the Crimson
Moon* background, rather than duplicating the wallpaper.

## Source and installed output

The exact user-approved `1672 × 941` image was converted to **lossless**
WebP before being stored in five ordered, base64-encoded files under
`themes/forge-eclipse/artwork-source/`. This works around the connector's
request-size limit without changing the image pixels.

`nix/artwork/forge-eclipse.nix` checks the compressed image's SHA-256
(`d68b0d18d2a804c2799b528b47737b66ad10c74c5afc4663d198923a35d7be7e`),
then renders a real **RGBA PNG at the native 1672 × 941 resolution** at
build time. The result is placed in the immutable Nix store; no
image conversion, download, daemon or file write happens at desktop login.

The files have separate purposes:

- **Wallpaper:** `nix/artwork/forge-eclipse.nix` produces
  `/etc/xdg/eduardos/forge-eclipse-wallpaper.png` for `swaybg`.
- **Installer:** `nix/artwork/forge-eclipse-installer.nix` produces a
  different, native-resolution `installer.png`, verified with SHA-256
  `91b2c9f7a02dc83f0033b9bdc63223f24d2074480cbd13ca2b38bad1cc469ff9`.
  The Nix wrapper passes this path to the fixed loopback `/artwork.png`
  route, with no browser-supplied filesystem path.
- **Boot menu:** Dedicated images are assembled by
  `nix/artwork/forge-eclipse-boot.nix` (PR #58).

All images are static PNGs in the Nix store. No background downloads or
runtime conversion occur.

The loader does not install or format any disk. The Forge GUI remains a
**read-only installation preview** until the separate Alpha 0.2 security
and installation milestones are implemented.

## Verification

```sh
nix build --no-link -L .#checks.x86_64-linux.theme-presets
nix build --no-link -L .#checks.x86_64-linux.live-iso-config
python3 -m unittest discover -s installer -p 'test_forge_gui.py'
```

For a visual acceptance test, boot the live ISO, verify that the Eclipse desktop uses its final wallpaper and that the Forge
preview uses the **different, installer-specific** artwork behind readable
text. Check the text contrast at both desktop and laptop resolutions. Check the preview remains unable to
execute installation operations.

**Branding:** `FORGED IN NEON` remains the overarching eduardOS motto.
`FORGED IN DARKNESS` is the distinct Forge Eclipse visual tagline.
