# PR #40 — Physical execution boundary: non-executable installation manifest

## eduardOS roadmap

Alpha 0.2 is our first **safely installable** target. Alpha 2.0
remains the longer-term distribution milestone.

PRs #31–#32 proved the real encrypted UEFI/Disko/NixOS installation and
login in a disposable QEMU disk. PRs #33–#39 implemented separate
read-only backend trust checks, credential memory, local process
authentication, physical-console consent, root-side one-shot behavior,
and actual adversarial root/non-root QEMU tests.

PR #40 adds a deterministic **root-held physical installation
intent manifest**. It deliberately does **not** add a privileged disk
writer. No physical installation is enabled by this change.

## Read-only preview contract

Optional flake package: `forge-physical-preview`

It is a command line tool for a trusted root process, **not installed
in the live ISO and not invoked by the GUI**. It reads exactly ONE
bounded `eduardos.forge.privileged.v1` `attest-target` JSON request from
stdin (as defined in PR #33). New fields and operations such as
`format`, `execute-install`, `command`, `script`, `password` or
`luks_key` are forbidden.

Usage for an independently reviewed fresh snapshot:

```sh
# Illustrative only: the input must originate from a fresh,
# independently root-verified Forge disk review.
sudo forge-physical-preview < verified-readonly-request.json
```

The command has **no execute mode**, target writer, Disko script
parameter, secret/credential transport, file output path or
privileged socket/API.

## What happens before a preview can be produced

1. Effective UID must be root **before reading request data**.
2. Apply the existing strictly versioned, bounded read-only JSON
   request parser and exact stable by-id disk confirmation.
3. Enter `forge_backend.prepare_target`: this independently verifies
   disk review freshness, Linux boot identity, live media provenance,
   active filesystem/swap ancestry and stable hardware identity.
4. Hold the selected **block device FD opened O_RDONLY** throughout
   the preview. It closes before the command returns any output.
5. Capture fresh `lsblk` and independently verify that the *whole
   disk review* still matches its current hardware, partition state,
   active mounts and boot session.
6. Revalidate the held descriptor's device number and stable by-id
   alias against that fresh snapshot.
7. Re-run the privileged guard on the *same fresh block graph*,
   checking active mount ancestry, swap and protected live media.
8. Capture and verify a **second fresh block snapshot** and held
   descriptor identity after the guard's slower checks.
9. Return an immutable-by-value **non-executable manifest** with the
   selected disk ID, review SHA-256 and current boot binding.

Every failed check refuses. There is **no rollback or destructive
operation to recover from**, because no writes occur.

These repeated reads detect many stale reviews, device replacements,
active mount/swap changes and hotplug races. They cannot make hotplug
impossible or create a physically atomic lock. A later separate
privileged disk writer must repeat independent checks at its exact
irreversible boundary.

## Descriptive intended storage and installation sequence

The manifest documents the intended eduardOS layout (as defined by
`nix/storage/disko-layout.nix` and the QEMU-tested installed profile):

| Planned phase | Intended result |
| --- | --- |
| `partition-gpt` | GPT partition table |
| `esp-vfat` | 1 GiB EFI system partition, VFAT |
| `encrypt-luks2` | LUKS2 encryption of the remaining target |
| `btrfs-subvolumes` | Btrfs @root, @home, @nix, @persist, @snapshots |
| `attest-mounts` | Verify six exact target mountpoints |
| `stage-account` | Stage a hashed user password in encrypted persist |
| `install-nixos` | Install the trusted NixOS system closure |
| `verify-boot` | Boot and verify encrypted user login |

These are **descriptions**. Every phase explicitly carries
`executable: false`. None contain a command string, argv,
shell snippet, disk writer FD, credential or executable callback.

Both the manifest and its wrapper carry all flags set to false:

- `write_operations_enabled`
- `destructive_disk_operations_enabled`
- `credential_writes_enabled`
- `authorization_to_write`

The `manifest_sha256` is SHA-256 of the canonical manifest and is
useful only for detecting accidental changes. It is **not** a
signature, signed authorization, secret token, non-repudiation
evidence, an approved disk plan, or authority to perform any write.

The script intentionally imports **no formatting engine** and has no
`install()`, `format_disk()`, `mount()`, `execute()` or
credential staging API. It is process-local and one-shot even when
the first attempt fails. No physical disk can be modified by it.

## Verification

Fast check:

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-physical-preview-tests
```

The tests use synthetic fixtures and mocks for device probing. They
cover deterministic hash and storage intent, exact mount/subvolume
set, NO-WRITE flags, missing executor operations, root denial before
reading the request, duplicate/unknown destructive parameters,
wrong disk/username/hostname/digest, stale review, refused ancestor
guard, held descriptor mismatch, hotplug between the two probes,
one-shot consumption and redacted refusal responses.

Previous PR #39 still tests root/non-root kernel identities and
socket permissions in an **actual disposable QEMU guest**. Its check,
along with the existing encrypted persistence, live ISO evaluation,
Hyprland and all fast tests, runs in normal pull-request CI.

**The full disposable QEMU installation workflow is not required to
validate PR #40** because it changes neither the destructive lab
executor nor the boot/storage configuration.

## What must happen before a physical installation exists

PR #41 and subsequent work need an independently reviewed execution
service, not just this read-only manifest:

- Explicit, authenticated operator intent tied to a current disk and
  trust-boundary call, *not* a manifest hash or socket PID alone.
- A narrow root-side writer that accepts only a fixed allowlist of
  audited operations, blocks shell/CLI injection, never accepts
  arbitrary targets, and keeps the device identity bound at the
  irreversible format boundary.
- Sealed LUKS/account secret transport with strict process
  authentication, short-lived buffers and no Nix-store/argv/env leaks.
- Abort, cancellation, timeout and partially formatted target
  recovery semantics: **no automatic retry**.
- Disposable adversarial end-to-end QEMU coverage, followed by
  explicit physical hardware safety review.
- Only then integrate the Forge GUI and ship the Alpha 0.2 ISO.

If the Disko layout changes, update and review this manifest in the
same change. This description is not a runtime guarantee that the
future disk writer uses the same storage configuration.

**eduardOS — Forged in Neon.**
