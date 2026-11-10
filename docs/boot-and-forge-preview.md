# eduardOS branded boot and installer-preview experience

## Boot paths

The live ISO continues to inherit the upstream NixOS minimal-ISO support
for UEFI, BIOS, initrd, squashfs and writable overlay, **but not the stock
look**. It identifies as **eduardOS — Forge Eclipse Live**, ships custom
EFI GRUB theme assets and BIOS Syslinux splash/label, and boots directly
to the Forge Eclipse Hyprland session.

On first graphical login, Forge Installer (Preview) opens in Brave. It is
an **unprivileged, loopback-only, token-protected, read-only application**.
It can inspect hardware and display proposed storage choices, but **cannot
partition, format, install, erase or authorize real disks**. Closing the
browser returns to the regular desktop. Use Fuzzel to relaunch
`eduardOS Forge Installer (Preview)`.

A physical installer is deliberately **not** enabled by this branding PR.
The future installation executor, consent and failure recovery milestones
in `docs/alpha-0.2-delivery-plan.md` remain release-blocking.

## Artwork

The boot background and installer colors follow the **original Forge
Eclipse vector artwork** from `themes/forge-eclipse/wallpaper.svg`.
These build into small static PNGs and GRUB files at image-build time.
There is no background animation or costly image conversion at boot.
Fallback text-mode GRUB boot and rescue consoles remain available.

## Verification

Run the lightweight check before spending compute on a full ISO:

```sh
nix build --no-link -L .#checks.x86_64-linux.live-iso-config
nix build --no-link -L .#checks.x86_64-linux.live-boot-theme
```

The final visual check must boot the **actual ISO** in both UEFI and BIOS
VM modes, confirm branded boot menu/desktop, confirm installer preview
says NO DISK WRITES, and confirm no destructive installer is available.
The normal headless serial smoke marker alone does not prove menu visuals.

⚡ eduardOS — Forged in Neon.
