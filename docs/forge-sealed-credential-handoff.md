# PR #35 — Sealed installer credential handoff rehearsal (no privileged transport)

## Roadmap context

PR #32 proved a real installed user and PAM login in disposable QEMU.
PR #33 added a *read-only* root-side physical-disk attestation protocol.
PR #34 established a one-shot, fail-closed transaction in disposable QEMU.

A production installer will ultimately need **both** a LUKS passphrase
and an installed account password. Passing either through command-line
arguments, environment variables, browser JSON, Nix expressions or
world-readable files is unacceptable.

This PR introduces **local, in-process Linux memfd credential primitives**
and a one-shot consumer API for the future trusted root-side installer.
It is intentionally **not yet a secure transfer between an unprivileged
GUI and privileged installer**. That transfer needs separately reviewed
caller authentication, consent, ownership checks and FD passing.

## Local producer and reader

`forge_credentials.sealed_luks_fd(...)` continues to offer the existing
sealed LUKS memfd API. A new `sealed_account_fd(...)` offers the
corresponding separate account password descriptor. Neither creates a
password file or calls cryptsetup.

`forge_secret_handoff.sealed_credential_pair(luks, account)` provides
a context-managed `CredentialFDs(luks, account)` pair. Each descriptor:

- Is created with Linux `memfd_create(MFD_ALLOW_SEALING|MFD_CLOEXEC)`.
- Has a fixed **role-specific label** (LUKS vs. installed account).
- Has `F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL` applied.
- Remains anonymous: no filesystem pathname or temporary secret file.
- Is closed on every exit path, including failure.

`OneShotCredentialReader(...).consume()` checks both descriptors
**before** returning any plaintext to its trusted caller:

1. Both inputs are integer FDs and are not the same underlying inode.
2. Both are regular, Linux anonymous memfds with the correct fixed role.
3. Both are `FD_CLOEXEC`, fully sealed, and 1–4096 bytes in size.
4. Contents are read with `os.preadv` into mutable `bytearray` buffers,
   leaving the FD's shared seek position unchanged.
5. FD identity, size, and all mandatory seals are verified again after
   each read. UTF-8 and the existing credential quality checks apply.
6. The consumer context zeroes the mutable buffers on both normal
   and exceptional exit. Even a **failed first attempt consumes** the
   one-shot reader instance, preventing a silent retry.

The role label helps avoid accidental swaps, **not** prove which process
created the memfd. A malicious process could create its own matching
label and seals; these checks cannot authenticate a sender.

## Scope and security limitations

No new executable or CLI is added to the live ISO, and nothing invokes
Disko, cryptsetup, NixOS installation, sudo, polkit, D-Bus, or a privileged
process. The module is neither imported nor callable by the browser
wizard or the root-only read-only preflight protocol.

No secrets are serialized in JSON, stored in Nix, included in process
arguments or environment variables, or emitted in logs.

**Python's immutable strings and transient runtime allocations are not
guaranteed zeroizable.** Mutable copies are wiped, but we must not
claim complete in-memory erasure. An eventual hardened implementation
could move the trusted credential consumer into Rust with controlled
buffers, audited IPC, process memory locking and explicit zeroization.

FDs can also be duplicated by a holder: "one-shot" means a given
`OneShotCredentialReader` instance accepts only one attempt, **not**
that a malicious process can be prevented from reading its own FDs.

Do NOT interpret possession of FDs, an attestation response, or an
already-verified disk review as authorization to erase a disk.

## Testing

Synthetic in-memory and ephemeral-memfd tests cover:

- Separate role labels and full Linux seal enforcement.
- Correct plaintext only during the consumer context and zeroized
  mutable buffers afterward.
- Early rejection of swapped, missing, duplicate, regular-file,
  oversized, unsealed, or non-CLOEXEC FDs.
- Short reads, second-credential failures and consumed readers.
- Validation of bad passwords or malformed inputs before producing FDs.
- Absence of privileged installer/formatting entrypoints.

Fast CI (no root privileges, ISO, physical media, or disposable VM):

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-secret-handoff-tests
nix build --no-link -L .#checks.x86_64-linux.forge-credentials-tests
```

Because the lab executor, QEMU test, disk layout, installed profile
and boot path are unchanged, a full encrypted installation workflow is
**not required specifically for PR #35**.

## Next milestone

Implement and independently review an authenticated local privilege
boundary that can receive FDs (not passwords in JSON) from a trusted
installer UI/CLI with explicit local consent. The physical-disk write
path must remain disabled until that boundary is tested against
symlink/device swaps, concurrent mount changes, failure/cancellation,
incorrect credentials and mixed user permissions.

**eduardOS — Forged in Neon.**
