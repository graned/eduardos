# Forge Installer — live ISO boot-media provenance (PR #26)

**Read-only diagnostic and protection logic only. No installer execution,
disk formatting, credential collection or new ISO build.**

## Problem being addressed

The Alpha 0.1 ISO boots a writable live desktop with an overlay root.
Unlike a directly mounted physical root partition, an overlay root's
major:minor device may be synthetic (e.g. `0:42`). PR #25's system-disk
guard correctly refused this setup: it could not safely identify what
disk or optical drive the live system was booted from.

PR #26 adds a *conservative* tracing path rather than bypassing the
protection.

## Evidence required

The reader examines the kernel mount table, active loop devices' sysfs
backing filenames, and `lsblk`'s block graph.

To recognize a supported live overlay, **all** of these must hold:

1. `/` is mounted as overlayfs and its `lowerdir`, `upperdir` and
   `workdir` are unambiguous.
2. Every lower layer corresponds to a mounted squashfs filesystem whose
   major:minor device identifies a known loop device.
3. Each squashfs loop has a kernel-reported absolute backing filename.
4. Every loop backing file resides **inside a mounted ISO9660 filesystem**,
   not on a regular writable disk filesystem.
5. The ISO9660 mount is backed by a known block device with a traceable
   physical disk or optical-media parent.
6. Overlay upper and work directories live on the same tmpfs mount.
7. The candidate target is not an ancestor of ISO media, other mounted
   filesystems, or active swap.

If any element is missing, duplicated, inconsistent, or unsupported,
the guard refuses. In particular, a loop-mounted ISO9660 file with no
traceable underlying physical disk does not qualify.

This is a **specific supported topology**, not a general overlayfs
resolver. Other NixOS ISO mount layouts and USB boot techniques may
legitimately be refused pending further testing.

## Read-only inspection

When testing on an environment with Nix installed:

```sh
nix run .#forge-live-media
```

On success, it prints the verified ISO9660 source major:minor numbers,
their protected physical/optical ancestors, and an explicit
`write_operations_enabled: false`.

The root-only preflight from PR #25 automatically attempts the same
proof *only* when it encounters an untraceable `/` mount.
It remains read-only and continues refusing unverified overlays:

```sh
nix run .#forge-disk-review -- --capture /dev/disk/by-id/EXAMPLE > review.json
sudo nix run .#forge-privileged-preflight -- --review review.json
```

The current Alpha 0.1 ISO **does not include these new tools**;
this PR adds packages and tests to the repository without triggering a
new image. Running them inside a live environment would require an
independently provisioned Nix command and network/cache access, or a
later strategic release image.

## What this does NOT prove

- It is **not** cryptographic verification of the ISO, boot chain, or
  filesystem contents.
- It is **not** a lock on the selected disk, a protection against device
  hotplug/replacement, or an authorization to erase anything.
- It does not support `tmpfs`/network/persisted overlays or arbitrary
  nested loop-file systems.
- It does not yet establish that the **actual Alpha ISO** uses this
  exact overlay-to-loop-to-squashfs layout. This requires a manual
  read-only mount inventory from the UTM test VM, followed by adaptation
  if necessary.

A future privileged writer must re-verify device identity and active
storage sources *immediately before* any disk operation and enforce
a separate consent boundary. A passing result from this tool must never
be treated as sufficient permission to write to physical media.

## Tests: fast and no ISO

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-live-media-tests
```

Synthetic fixtures include ISO boot from a disk partition and optical
drive, rejection when the target is boot media, missing/untracked loop
backing, lower layers on the wrong filesystem, persistent overlay
upper/work layers, extra lower layers, missing root, loop-only
ISO9660 backing, and sysfs path parsing.

The existing encrypted storage, QEMU installation and graphical smoke
checks remain unchanged.

## Next step

Capture the real Alpha ISO's mount topology using read-only commands
(`findmnt`, `lsblk`, `/proc/self/mountinfo`,
`/sys/block/loop*/loop/backing_file`) on an isolated VM. Confirm the
provenance logic matches the actual ISO before any attempt to integrate
physical installation.
