# PR #34 — One-shot fail-closed installation transaction (QEMU ONLY)

## Why

PRs #22–#32 proved real, encrypted eduardOS installation and account login
on disposable QEMU disks. PR #33 added a completely **read-only** root-side
attestation protocol for future physical installations.

Before any physical-write capability exists, we must define what happens
at the irreversible formatting boundary and verify that a failed step can
never accidentally continue into password staging or `nixos-install`.

This PR extracts a strictly ordered transaction state machine and uses it
inside the **existing QEMU-only** installer executor. It does NOT connect
the physical attestation protocol to a writer.

## Exact lab transaction

The one-shot `InstallationTransaction` performs these stages:

| Phase | Action | Possible physical writes? |
| --- | --- | --- |
| `guarded` | Revalidate QEMU root/marker, /dev/vda, ancestry and held descriptor | No |
| `format-started` | Mark the irreversible boundary **before** invoking Disko | Not yet, but now possible |
| `formatted` | Existing QEMU-only Disko returned successfully | Yes, disposable /dev/vda |
| `mounted-attested` | Verify all six exact mounted EFI/Btrfs sources | Read-only check |
| `credential-staged` | Write SHA512-crypt hash to audited encrypted persist | One hash on QEMU target |
| `re-attested` | Re-run exact encrypted mount audit after credential staging | Read-only check |
| `install-started` | Invokes only the existing fixed `nixos-install --root /mnt` | QEMU installation |
| `installed` | Installation process succeeded | QEMU only |

There is no user-controlled step list or injected executable command. The
lab executor passes known Python callables to the transaction; the
transaction itself imports **no** disk, subprocess, filesystem or
credential module and has **no CLI, socket or permission elevation**.

The VM safety guard is checked twice: once by the existing installer
at the request boundary and again inside the held block-device
descriptor's lifetime, immediately before Disko can be invoked.

## Failure handling

A transaction is consumed on its **first attempt**, including a failed
preflight. It cannot be run again, resumed, or rolled back.

If a check fails before `format-started`, the terminal phase is
`halted-before-format`; no formatter was invoked.

If anything fails at/after `format-started`, the terminal phase is
`halted-after-format-started`. A partially formatted target is
possible, even if Disko returned an error. Recovery must be a separate,
explicitly reviewed fresh installation; **never silently retry, unmount,
wipe, restore or reuse an old review**.

In particular:

- Mount attestation failing prevents both password staging and
  `nixos-install`.
- Credential staging failing prevents `nixos-install`.
- A second mount audit failing after password staging prevents
  `nixos-install`.
- An installation failure is surfaced and is not automatically retried.
- Progress lines contain **only** `FORGE_QEMU_PHASE=<fixed phase>` and
  do not contain passwords, account names, device paths, hash values,
  arbitrary exception messages or user-controlled text.

## Tests

Pure, in-memory `test_forge_install_transaction.py` injects failures
at every step, validates monotonic phase order and both terminal failure
states, verifies the second mount audit, and rejects attempts to repeat
a transaction or supply missing callbacks.

`test_forge_executor_lab.py` uses fake Disko and install subprocesses
to confirm the second QEMU guard, held disk identity, failure-stop
semantics and two audits; **it cannot touch a real disk**.

The full `uefi-installed-boot` QEMU integration test also asserts that
every expected phase appears in strict order and is followed by normal
UEFI/LUKS2/PAM boot and cold-reboot checks.

Fast PR CI checks:

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-install-transaction-tests
nix build --no-link -L .#checks.x86_64-linux.forge-installer-lab-tests
```

This performs **no ISO build**.

Before merging this PR, run the **separate full encrypted installation**
workflow on the PR branch (same manual check as PR #32) because the VM
destructive test path has changed.

## Still deliberately missing

- Physical hardware formatter and safety-reviewed trusted execution.
- Physical-disk credential collection and sealed secret transport.
- A privileged GUI-to-backend protocol or polkit authorization.
- Production install cancellation/recovery user experience.
- An Alpha 0.2 installable ISO.

The existing `forge-privileged-protocol` from PR #33 remains strictly
**read-only** and has no access to this transaction's operations.

**eduardOS — Forged in Neon.**
