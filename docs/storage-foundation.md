# eduardOS storage foundation (PR #15)

This milestone introduces a **guarded, destructive prototype provisioner** and
a real QEMU **data-disk persistence** test. The desktop VM is intentionally
unchanged. **This is not yet a bootable installed NixOS disk image.**

## Target storage design

- GPT partition table
- 1 GiB FAT32 EFI System Partition (`EDOS-EFI`)
- Remaining disk encrypted with LUKS2 (`edos-crypt`)
- One Btrfs filesystem (`edos-system`) with five independently mounted
  subvolumes:

| Btrfs subvolume | Planned mountpoint | Purpose |
| --- | --- | --- |
| `@root` | `/` | Replaceable OS root |
| `@home` | `/home` | Personal files and app configuration |
| `@nix` | `/nix` | Nix store and reproducible packages |
| `@persist` | `/persist` | Explicit durable system state |
| `@snapshots` | `/.snapshots` | Future rollback snapshots |

All five subvolumes share the available Btrfs capacity; they are *not*
separately sized partitions. `compress=zstd,noatime` is used when mounting
them in the integration test. Encryption protects against offline disk
inspection but is not a backup and does not substitute for recovery keys.

## QEMU integration test

```sh
nix build .#checks.x86_64-linux.storage-persistence -L
```

This starts a NixOS guest with a separate, disposable 4 GiB block disk,
requires a key file and explicit destructive flag, creates GPT + LUKS2 +
Btrfs, closes/reopens the encrypted volume, writes markers to all five
subvolumes, reboots the guest, reopens the volume and verifies the markers
survived. The original Hyprland and screenshot tests continue unchanged.

## Destructive tool — not a first-boot installer

The packaged `edos-storage-provision` command requires **both**
`--destroy-disposable-disk` and an `EDOS_LUKS_KEYFILE` environment
variable naming an existing, nonempty file. It refuses any mounted disk
or one with active crypt/LVM/RAID mappings. This does **not** make it safe
for arbitrary real disks: the operator is still responsible for selecting
the correct target, maintaining recovery keys and backups, and accepting
that **all data on the target disk will be permanently destroyed**.
Do not run it on an existing installed system or on a real disk with
valuable data.

The test uses a synthetic throwaway key. No key, password, or recovery
credential is committed for real installations.

## Next milestones / explicit exclusions

1. Adopt a pinned, declarative **Disko** layout for the real installer,
   including a documented migration plan and explicit disk selection.
   Disko already supports GPT, LUKS and Btrfs and should be preferred to
   building a partitioning engine in Rust.
2. Build and boot an **actual installed UEFI disk image**, verify initrd
   unlock and interactive passphrase flow, and exercise reboot/upgrade.
3. Add snapshot/rollback policy and test backup/restore for `@home`
   and `@persist`, including a recovery procedure.
4. Build a Rust `edos` CLI for orchestrating installation, showing a
   dry-run plan and inspecting system state **without implementing
   partition manipulation or replacing systemd**.

The installer, secure boot, snapshots, backups, automated upgrade rollback,
and physical hardware compatibility are **not yet implemented**.
