# Forge Installer — root-only physical-disk preflight (PR #25)

**Security foundation only: no formatting, mounting, installation, credential
handoff or disk-writing capability. Not included in any ISO.**

PR #25 adds a root-only read-only program used to assess whether a selected
blank disk could be backing the currently running OS or another mounted
filesystem. It builds on the existing stable by-id identity review from
PR #23 and the local confirmation prototype from PR #24.

## Why a new check?

Simply checking whether `/dev/sda` is mounted is insufficient. A system
could actually boot from `/dev/mapper/edos-crypt` whose underlying block
device is `/dev/nvme0n1p2`. RAID1 and other multi-parent configurations
can have multiple physical disks behind a single mounted filesystem.

This preflight uses major:minor identities from `lsblk` and the Linux
kernel's mount table. It builds every discovered parent-child edge and
protects **all ancestors** of every mounted block device and active swap
device. It never trusts `/dev/sdX` naming as durable identity.

## What the helper verifies

1. Caller is root, but elevated privileges do **not** grant write access.
2. Existing disk-review JSON remains valid according to
   `forge_disk_identity.verify`, including stable id, model, serial/WWN,
   capacity, boot ID and blank-disk restriction.
3. Inventory is freshly probed again; review verification must still pass
   against the exact topology subsequently analyzed.
4. The target is exactly one whole disk in the `lsblk` graph.
5. Every mounted block device is mapped to its physical parents, including
   partitions, dm-crypt/LVM and shared mdraid ancestry.
6. Every active swap source must resolve to a block device; unresolvable
   sources, including file-based swap, cause a refusal.
7. If any critical filesystem (/, /boot, /nix, /home, /persist) has an
   unknown underlying device, the check refuses rather than guessing.
8. Candidate disks that back mounts or swap are refused.

## Running the *read-only* helper

On Linux x86_64 with Nix:

```sh
nix run .#forge-disk-review -- --capture /dev/disk/by-id/EXAMPLE > review.json
sudo nix run .#forge-privileged-preflight -- --review review.json
```

The helper returns `status: preflight-passed` and
`write_operations_enabled: false` only if all checks pass. It never
executes Disko or `nixos-install`. Its review-file reader uses
`O_NOFOLLOW`, regular-file checks and a 128 KiB limit; JSON remains
**untrusted input**.

**Important:** The current Alpha 0.1 live desktop uses an overlay root.
The backing media cannot yet be traced reliably by this generic mount
graph, so the helper deliberately refuses that scenario. Live-media
detection, verified media provenance, and an explicit installation
environment profile need their own reviewed implementation before
using this guard in the installer ISO. Do not bypass the rejection.

## No ISO, no destructive tests

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-privileged-preflight-tests
```

The fixture suite exercises:

- Normal blank target distinct from system disk.
- Encrypted root under a partitioned physical disk.
- Mounted EFI partition.
- mdraid with two physical parents.
- Active swap on a candidate disk and unknown swap files.
- An overlay root or missing/unknown root mount.
- Mounted noncritical filesystems.
- Conflicting/incomplete device graphs.
- Non-root caller refusal and fresh identity verification.
- Review JSON symlink/oversized-file rejection.

The program runs no disk-writing operations and is not connected to the
browser UI or the QEMU-only destructive executor.

## Remaining work before Alpha 0.2

The **future privileged writer** must independently revalidate hardware
and currently active media *immediately before writing*, prevent device
path replacement (including by-id symlink races), use a validated
device/partitioning plan, collect LUKS and user secrets through a secure
local interface, and support the live ISO's verified boot media. A
success from this module is not proof against time-of-check/time-of-use
changes and is never authorization to erase any drive.

Until then, physical installation remains intentionally unavailable.
