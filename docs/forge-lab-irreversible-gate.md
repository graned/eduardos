# PR #43 — Real QEMU irreversible Disko boundary

## Roadmap

Alpha 0.2 is our first safely installable encrypted eduardOS release,
on the long-term route to **Alpha 2.0**.

PR #42 defined a non-executable fixed-argument QEMU-only command review
and a read-only kernel mount/swap/boot ancestry check. PR #43 now
**integrates those checks with the actual disposable-QEMU installer**,
immediately before its first disk-formatting command.

## QEMU-only integration

The only destructive executable remains
`installer/forge_executor_lab.py`. It is **not installed in the live
ISO** or connected to the Forge GUI or physical root preflight.
The exact disk is still hardcoded to **`/dev/vda`**. The existing
root check, independent QEMU/KVM/Bochs DMI check, test-only marker,
LUKS key fixture, exact disposable-disk confirmation, strict input
credentials, current kernel mount ancestry, O_RDONLY held disk FD
and fail-closed one-shot transaction all remain mandatory.

### Exact execution policy

After the existing independent safety gates and credential input
validation, the runner calls the *non-executable*
`forge_lab_command_policy.review_commands`. It rejects
unexpected paths or commands and compares the returned review
against the exact fixed two-command contract. Its fields must
explicitly say **no writes are authorized**.

- Disko invocation: the independently evaluated Nix-store Disko
  formatter script, with only `--yes-wipe-all-disks`.
- NixOS invocation: the existing `nixos-install --root /mnt
  --system <Nix-store closure> --no-root-passwd` argument list.

The review is a consistency guard **inside the pre-existing QEMU
authorization**, not permission granted by a hash or file path.
Command execution remains in the original guarded lab module, not
in the contract module.

### Before the irreversible format call

The one-shot transaction first rechecks the QEMU environment, held
kernel disk identity and fixed root/user confirmation; then it enters
`format-started` **before calling any formatter**. Inside the
existing `format_disposable()` callback, immediately before Disko:

1. Prove `os.fstat(held_fd)` still identifies the exact kernel
   `major:minor` of the fixed `/dev/vda` path.
2. Collect a **new** `lsblk` block graph from the kernel.
3. Read **current** `/proc/self/mountinfo` and `/proc/swaps`.
4. Collect actual loop-backed live-media identities from sysfs.
5. Invoke the PR #42 read-only guard on all four fresh sources,
   rejecting active mounts/swap, root/live-media ancestry, changed
   device numbers, or any permission change.
6. Reject if the guard is not an exact read-only success for the held
   disk.
7. Prove the held block FD and the disk alias still agree **again**.
8. Only then invoke the existing QEMU Disko script once.

A concurrent physical hotplug is not prevented atomically by these
checks; real-hardware writers will require a more strongly designed
kernel device binding and an independently audited execution model.
No physical-disk write code is added here.

### Partial failure semantics

The existing `InstallationTransaction` is single-use. A failure
in this newly integrated pre-Disko check (or inside Disko) emits
`halted-after-format-started` because the transaction entered
the irreversible phase. This is conservative; if the audit fails
before Disko, it has not written a disk, but callers must never
assume that every interruption guarantees pristine storage.

**No automatic retry, resume, rollback, or format-after-failure** is
permitted. Once Disko succeeds, existing mount identity checks,
encrypted user hash staging, repeated mount attestation and NixOS
installation remain enforced.

## Verification

The new fast `forge-irreversible-gate-tests` check mocks all disk
and subprocess operations and injects:
- changed held FD before/after the block probe;
- changed kernel target device number;
- mounted root/live media or active swap reported by the guard;
- malformed/privilege-escalated guard reports;
- altered Disko/NixOS command policy;
- Disko subprocess failure at the irreversible boundary;
- no call to Disko after a failed independent read-only audit;
- terminal failure state with no retries or continuation.

Run the lightweight tests:

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-irreversible-gate-tests
nix build --no-link -L .#checks.x86_64-linux.forge-installer-lab-tests
nix build --no-link -L .#checks.x86_64-linux.forge-lab-command-contract-tests
```

**Unlike PR #42, PR #43 changes actual destructive QEMU installation
code.** The full encrypted installation workflow must pass on this
branch before merging:

```sh
nix build --no-link -L .#checks.x86_64-linux.uefi-installed-boot
```

The `eduardOS full encrypted installation` workflow now triggers
automatically on PRs modifying installer execution/security, storage
layout, or installed boot tests, **not theme-only or documentation
PRs**. It uses a throwaway qcow2 disk, real Disko formatting, real
LUKS2/Btrfs, UEFI/OVMF cold boot and account PAM login; it never
opens a host disk.

The usual fast, root/non-root adversarial VM, encrypted persistence
and desktop CI checks remain required.

## Not production hardware authorization

This PR retains exactly the old QEMU-only destructive capabilities.
It does **not** connect or install the lab executor into the live ISO,
enable physical-drive writes, accept arbitrary selected disks,
expose any sudo/polkit endpoint or connect browser UI to root.
No real passphrases are used. The test runner's marker and public
fixture secrets are insufficient as physical consent mechanisms.

**Next:** disposable-QEMU failure/recovery acceptance tests,
narrowly scoped root-side physical execution design, and strong
credential and human-presence authorization review.

⚡ **eduardOS — Forged in Neon.**
