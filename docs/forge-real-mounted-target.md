# Forge Installer — Real Mounted-Target Audit (PR #30)

**Read-only audit of a real disposable QEMU encrypted disk.**
This adds no physical installation route, ISO build, credential-writing command,
or new disk format operation outside the existing, explicitly disposable
NixOS storage integration test.

## Why PR #30

PR #29 introduced a fail-closed mounted-target checker, but the inputs in
its unit tests were synthetic. Linux `lsblk`, `/proc/self/mountinfo`,
Btrfs mount root paths and dm-crypt relationships must be verified against
a genuinely formatted and mounted block device before treating the
checker as reliable.

## New read-only CLI

`forge-mount-audit --disk /dev/vdb` asks the kernel and `lsblk` about
the **already-mounted** target, then delegates to the PR #29
`attest_target_mounts` verifier. It checks:

- The requested path is exactly one whole disk in the current block graph.
- The kernel major:minor block device matches `lsblk`'s selected disk.
- The `edos-crypt` mapper's physical backing is exclusively that disk.
- The five Btrfs mounts are sourced from that mapper and correspond to
  the exact `@root`, `@home`, `@nix`, `@persist`, `@snapshots`
  subvolumes.
- The EFI vfat partition is on the same selected disk.
- No installed mount is missing, duplicated or unexpectedly nested under
  `/mnt`.

The output explicitly marks both `destructive_disk_operations_enabled`
and `credential_writes_enabled` false. **Passing this check is evidence,
not authorization for disk writes.**

The command cannot format, mount, install NixOS, erase a device or create
password files. It does not connect to the graphical wizard.

## Actual QEMU integration

The existing `checks.x86_64-linux.storage-persistence` NixOS VM test
already provisions a disposable QEMU `/dev/vdb` with EFI + LUKS2 +
Btrfs. This PR extends *that same test* to:

1. Unlock `edos-crypt` with a disposable test-only credential.
2. Mount the actual five encrypted Btrfs subvolumes at the Disko
   destination locations and the EFI partition at `/mnt/boot`.
3. Run `forge-mount-audit --disk /dev/vdb` on real kernel data, and
   verify the returned target and read-only security status.
4. Assert failure if the selected disk is changed to the guest system disk.
5. Assert failure after unmounting `/mnt/persist`; remount and verify
   it succeeds again.
6. Assert failure after fully unmounting the target.
7. Continue the original cold-boot persistence checks, ensuring no
   regression.

Only the disposable guest disk is ever formatted, through the already
existing disposable storage test. The new auditor runs only
non-destructive inspections.

## Verification commands

Fast synthetic checks (ordinary PR CI):

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-mount-audit-tests
```

Real encrypted mount integration (existing PR storage job, no ISO):

```sh
nix build --no-link -L .#checks.x86_64-linux.storage-persistence
```

This is a QEMU test; it needs a Linux builder with KVM support. It is
already part of the existing `Encrypted data persistence and boot` job.
No slow ISO build or new scheduled job is added.

## Known boundaries

- The audit does not prove that a USB live system is cryptographically
  authentic or that the kernel disk identity cannot change after checking.
- This test does not install the **new real-user profile** or exercise
  username/password activation; those are later end-to-end goals.
- For physical installation, the future isolated privileged writer must
  repeat disk identity and mount ancestry checks at the point of use.
- A test success does **not** enable the graphical installation action.

**Next after PR #30:** Use the real mount test results to harden the
privileged installation protocol; then integrate the guided wizard with
an audited disposable-VM-only execution path before Alpha 0.2 release.
