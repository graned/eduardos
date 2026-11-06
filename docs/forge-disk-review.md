# Forge Installer — Physical disk identity review (PR #23)

**Read-only identity gate, not a physical installation executor.**

Alpha 0.2 work is progressing in small validated pull requests. This
change adds a *reusable review contract* for a future privileged installer
and deliberately does not enable disk writes, the VM lab executor, or any
HTTP write endpoint.

## Why identity matters

Disk naming can change between discovery and installation. An innocent
`/dev/sdb` might later point to a completely different drive. Even a
stable `/dev/disk/by-id` symlink must be resolved again immediately
before an operation that could destroy data.

The earlier preflight intentionally only evaluated whether a disk might
be a candidate. The new disk review adds:

- An explicitly selected `/dev/disk/by-id/...` identity.
- Identity attributes: path, exact byte size, model, serial, WWN,
  transport, major:minor device number, partition-table signature,
  read-only/removable status and NixOS storage layout description.
- A boot-session UUID, so a reboot invalidates an old review.
- A deterministic SHA-256 fingerprint for detecting accidental changes
  in the stored JSON document.
- Fresh hardware enumeration on verification: any difference blocks the
  previous review and requires starting over.
- A **blank-disk-only** initial policy. Existing partitions, storage
  signatures, swap, mounts, active encrypted/RAID/LVM mappings, missing
  hardware identifiers, and insufficient hardware checks are blocked.
- No root privileges, credential collection, formatting, mounting,
  `nixos-install` or destructive operations.

## Commands

On Linux x86_64 with Nix, discover exact stable identifiers first:

```sh
nix run .#forge-installer -- --json
```

Create a read-only review for a deliberately selected blank drive:

```sh
nix run .#forge-disk-review -- --capture /dev/disk/by-id/EXAMPLE > review.json
```

Before proceeding with any future installation workflow, re-probe:

```sh
nix run .#forge-disk-review -- --verify review.json
```

An eligible review exits 0 and prints `"verified": true`;
a blocked review or changed device exits 2 and produces an explanation.
The `review.json` file is **not** a permit to erase any drive.

The fingerprint is **not a digital signature or authorization token**.
An untrusted process could generate a different JSON file and hash.
The future privileged installer must independently re-enumerate the
device, enforce protection against current root/boot and related
physical devices (including mapper and RAID ancestry), obtain explicit
user authorization in its own trust domain, and verify hardware again
immediately before any destructive operation. This review is a defense
in depth / design and testing foundation, not a replacement.

This initial policy only permits a disk with no partition table or
children; migration, reinstallation, dual boot, and intentionally
wiping existing media require their own separate threat model, review,
backup checks and user consent.

## Fast tests

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-disk-review-tests
```

Fixture cases: disk size/model/serial/WWN/device-number changes, boot
session change, missing or duplicated by-id IDs, partitions, mounts,
swap, read-only media, missing hardware serial/WWN, invalid schema,
fingerprint mismatch and explicit read-only guarantees.

No ISO is built. The graphical preview remains read-only, and the
destructive QEMU lab executor from PR #22 remains separate.
