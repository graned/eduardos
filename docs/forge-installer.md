## Graphical Forge Neon wizard — PR #21

The graphical installer is a **responsive, local-only browser UI**, using
the existing PR #20 `forge_installer.py` disk discovery and safety rules.
There are no GTK dependencies, no root requirement, and no new services
enabled on the host or live ISO.

### Start the UI on a Linux desktop with Nix

```sh
nix run .#forge-installer-gui
```

The command starts a Python standard-library HTTP server bound to
`127.0.0.1` on an ephemeral port and opens your browser. If automatic
browser launching fails, use:

```sh
nix run .#forge-installer-gui -- --no-browser
```

Then open the printed local URL in your browser. The browser URL contains
a random access token; treat it like a local secret and don't share it.
Press Ctrl+C to shut down the server.

The wizard contains four screens:

1. **Welcome** — release context and explicit dry-run warning.
2. **Hardware** — x86_64, UEFI, RAM checks.
3. **Storage** — discovered disk candidates, model, capacity and
   detailed reasons for blocking unsafe selections.
4. **Review** — freshly revalidated selected stable device ID and
   the proposed EFI / LUKS2 / Btrfs layout.

The wizard is a **preview**, not an installer. Only HTTP GET requests
are supported. No password fields, privilege escalation, partitioning,
formatting or mount actions are available. The backend uses a
fixed whitelist of static files, an access token for the read-only API,
a local bind and Host-header validation. The UI uses `textContent` for
disk labels to avoid interpreting device metadata as HTML.

### Tests, no ISO

```sh
nix build --no-link .#checks.x86_64-linux.forge-installer-gui-tests
```

Fast CI runs loopback API/security tests with synthetic device fixtures:
the launch token, API token, Host header checks, no write HTTP verbs,
stable disk identifier selection and fail-closed missing-device checks.

This package is deliberately **not embedded into Alpha 0.1's ISO**.
We'll integrate it into the release ISO once the execution workflow and
disposable-VM installation tests are complete, and only then produce
the Alpha 0.2 ISO. The existing terminal wizard remains available.

---

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
