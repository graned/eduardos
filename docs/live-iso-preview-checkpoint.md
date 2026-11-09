# Alpha 0.1 Preview Build #2 — boot and inspect eduardOS

The live ISO is a **non-installable preview**: it has no physically
authorized disk writer and does not import the Disko installation target.
It is for experiencing the Forged in Neon desktop and read-only Rust CLI.
The installable Alpha 0.2 remains a separate milestone.

## Build using GitHub

1. Open **Actions → eduardOS Alpha live ISO → Run workflow**.
2. Choose the merged main branch (or the PR branch to test an unmerged change).
3. Wait for `Build bootable eduardOS Alpha ISO` to complete.
4. Download the `eduardos-alpha-live-iso` artifact and extract its parts.

The manual workflow evaluates the live profile, builds the real ISO, then
boots it in **diskless QEMU** and waits for the live-only serial
`EDOS_LIVE_BOOT_OK=alpha-0.1-preview` acknowledgement. It uploads
split ISO parts, `SHA256SUMS`, and `BUILDINFO.txt` only if the build
and boot smoke check succeed.

The QEMU smoke check verifies a Linux boot to multi-user state, **not**
that Hyprland renders correctly or that an installation works.
Visual desktop acceptance is a separate manual step.

## Reassemble and verify

On a Linux computer with `sha256sum`:

```sh
bash scripts/reassemble-live-iso.sh ~/Downloads/eduardos-alpha-live-iso
```

This reconstructs `eduardos-alpha.iso` in the artifact directory,
checks its SHA-256 against `SHA256SUMS`, and refuses to retain a bad
reconstruction. Inspect `BUILDINFO.txt` for the exact source commit.

## Boot for visual review (recommended: virt-manager)

Import `eduardos-alpha.iso` as a read-only CD-ROM in a **new disposable
virtual machine**, using UEFI if available. Allocate about 4 GiB of
RAM and 2+ CPUs. You do not need to add a virtual hard drive.
Enable 3D graphics/Wayland support if your hypervisor supports it.

The live session should launch Hyprland as the `forge` user.
If the graphical session fails, the fallback greeter can be used.
The live password is `forge` (public preview fixture only).
No part of this preview should be allowed to select or format a disk.

Review and record:
- Initial boot and login; unexpected errors.
- Neon/Tlaloc wallpaper and Forge brand identity.
- Hyprland keyboard shortcuts, launcher and Ghostty transparency.
- Catppuccin appearance and basic terminal/editor usability.
- `edos version`, `edos status`, `edos doctor` in the live terminal.
- Responsiveness, CPU/memory behavior, and any missing packages.

For an optional **headless boot-only** test on Linux/KVM:

```sh
bash scripts/smoke-live-iso.sh ~/Downloads/eduardos-alpha-live-iso/eduardos-alpha.iso
```

This command boots a diskless VM, checks only the serial boot marker,
then terminates QEMU. It does not validate the graphical desktop.
No disk passthrough or physical device path is used.

## Local build, if preferred

```sh
nix build --out-link result --print-build-logs .#live-iso
find -L result/iso -maxdepth 1 -name '*.iso'
```

ISO builds can be large and slow. They are intentionally **manual**,
not part of every PR. Build and boot checks must pass before presenting
a particular artifact as a verified preview.
