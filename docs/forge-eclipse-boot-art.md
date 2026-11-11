# Forge Eclipse dedicated boot menu artwork

The **boot/NixOS installation media menu** now uses the approved
`crimson_eclipse_over_ruined_mountains.png` art rather than the old
Eclipse vector wallpaper.

This is a **separate asset** from the Forge Eclipse desktop wallpaper
and the Forge graphical installer background. Neither of those is
modified here.

## Source and output

For reliable GitHub uploads, the 1672 × 941 approved PNG was encoded
losslessly as WebP and split into ordered base64 source fragments in
`themes/forge-eclipse/boot-source/`.

At Nix build time, `nix/artwork/forge-eclipse-boot.nix` verifies its
SHA-256 before converting into PNGs:

- **BIOS Syslinux:** 800 × 600 (`bios.png`)
- **UEFI splash:** 1280 × 720 (`efi.png`)
- **GRUB theme:** 1280 × 720 (`grub.png`)

Source checksum: `c65bed422ee974a33bfd5d2b7908c91aa1307634bc34cad61b5b060886810811`.

Pillow's high-quality Lanczos resampling fills each target canvas
without stretching subjects. The PNG conversion happens only at
build time; the live environment requires no image-conversion daemon.

## Verification

```sh
nix build --no-link -L .#checks.x86_64-linux.live-boot-theme
nix build --no-link -L .#checks.x86_64-linux.live-iso-config
```

After CI passes, build the ISO using the normal release workflow and
visually check the **actual boot menu** in both UEFI and BIOS VM modes,
including menu readability and fallback navigation.

Desktop wallpaper, Forge preview and all disk-installation safety
boundaries are unchanged by this PR.
