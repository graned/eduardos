# Forge Eclipse — approved final wallpaper and installer art

The Forge Eclipse desktop and the unprivileged Forge installer preview share
the **same approved artwork**, featuring the crimson eclipse, the God Hand,
Guts, sacrifice mark, eduardOS logo and **FORGED IN DARKNESS** legend.

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

The following use that same built PNG:

- Hyprland/`swaybg`: `/etc/xdg/eduardos/forge-eclipse-wallpaper.png`
- Forge GUI: fixed loopback `/artwork.png` route (the Nix wrapper passes a
  trusted immutable image path, never a URL or path from the browser)

The loader does not install or format any disk. The Forge GUI remains a
**read-only installation preview** until the separate Alpha 0.2 security
and installation milestones are implemented.

## Verification

```sh
nix build --no-link -L .#checks.x86_64-linux.theme-presets
nix build --no-link -L .#checks.x86_64-linux.live-iso-config
python3 -m unittest discover -s installer -p 'test_forge_gui.py'
```

For a visual acceptance test, boot the live ISO, verify that the Eclipse
desktop uses the final wallpaper and that the Forge preview uses the
same artwork behind readable text. Check the preview remains unable to
execute installation operations.

**Branding:** `FORGED IN NEON` remains the overarching eduardOS motto.
`FORGED IN DARKNESS` is the distinct Forge Eclipse visual tagline.
