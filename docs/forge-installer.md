# Forge Installer — PR #20 (read-only foundation)

**Status: preview / dry-run only. This version never installs eduardOS.**

Alpha 0.1 boots as a live ISO; it does not include an installer.
PR #20 introduces a terminal-based installer preflight packaged as
`packages.x86_64-linux.forge-installer`. It is intentionally **not added
to the Alpha 0.1 ISO**, because full ISO builds happen only at release
milestones.

## Run on x86_64 NixOS/Linux with Nix

```sh
nix run .#forge-installer
```

This displays the Forge-style hardware summary, eligible and blocked disks,
and (after entering a disk number) the proposed storage layout. Nothing
is executed against the selected disk. Press Enter to cancel.

For machine-readable discovery:

```sh
nix run .#forge-installer -- --json
```

To preview a previously discovered **stable** identifier:

```sh
nix run .#forge-installer -- --disk /dev/disk/by-id/virtio-EXAMPLE
```

The `--disk` argument accepts only an exact identifier obtained from
`/dev/disk/by-id/` discovery. It does not accept arbitrary `/dev/sda`
paths or user-supplied paths not present in the inventory. **The selected
disk is never opened for writing.**

## Read-only preflight rules

- x86_64 Linux architecture, UEFI boot, at least 4 GiB RAM.
- Whole block disks must be at least 32 GiB and have a stable `by-id` link.
- Blocked by default: mounted disk/descendants; swap; active LVM, RAID
  or dm-crypt descendants; read-only or removable devices.
- Device discovery reads `lsblk --json --bytes` and `/sys`,
  `/proc/meminfo`, and symlinks under `/dev/disk/by-id`.
- Eligible means **candidate for further review**, not guaranteed safe
  to erase. The eventual installer must re-check the selected disk,
  model, serial, size, mounted descendants and ownership immediately
  before any destructive action.

Proposed storage layout reuses `nix/storage/disko-layout.nix`:
1 GiB EFI System Partition, remaining LUKS2-encrypted Btrfs,
subvolumes `@root`, `@home`, `@nix`, `@persist`, `@snapshots`.

The output explicitly reports `"would_write_to_disk": false`, with
`"mode": "dry-run-only"`. There is no `--execute` / `--install`
flag, formatter, partitioning call, disk mount, password collection,
`nixos-install`, or privilege escalation.

## Tests (no ISO)

```sh
nix build --no-link .#checks.x86_64-linux.forge-installer-tests
```

The fast GitHub CI job runs this check with synthetic `lsblk` fixtures.
It tests disk selection, mounted partitions, active encryption, swap,
read-only/removable/small/missing-ID devices, unsupported boot/CPU/RAM
configurations, and JSON output. Tests are unprivileged and do not inspect
or modify the CI runner's disks.

## Future PRs

- Graphical Forge Neon installer using the same read-only preflight model.
- User account and LUKS passphrase collection with secure handling.
- Revalidation and explicit, unambiguous consent before disk erasure.
- Disko-based formatting and NixOS installation in a **disposable VM**
  followed by cold-boot and persistence tests.
- Only **after** those checks pass: build the Alpha 0.2 ISO and test it
  manually in UTM.

**Do not use `nix/storage/provision.sh` on a personal machine.** It is a
separate destructive storage prototype for disposable testing, not this
installer.
