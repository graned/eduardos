# PR #41 — One-shot read-only execution and sealed-credential integration

## eduardOS roadmap

Alpha 0.2 is the next installable release milestone, on the path to
**Alpha 2.0**. PRs #32–#40 established a QEMU-proven encrypted
installation, root-only read-only disk verification, one-shot
local approval, a physical-VT consent mechanism, Linux peer-authenticated
Unix FD transport, adversarial QEMU tests and a deterministic,
**non-executable** physical installation preview.

PR #41 combines these *separate boundaries* into one testable
**root-side execution rehearsal** before attempting a physical writer.
This is an in-process integration **library**, not a running service.
It remains physically impossible to format a disk through its API.

## Exact trust sequence

The new `installer/forge_execution_rehearsal.py` exposes
`OneShotExecutionRehearsal(TrustedIntent).run(preflight_conn,
credentials_conn)` to a future trusted root-controlled invoker.

The trusted intent is the existing PR #37 object, created independently
by the root process, binding an exact Linux PID/UID/GID peer, selected
disk review, boot ID, account identity, host identity, 120-second
deadline and a separate root-side local approval callback.

On its FIRST attempt (even if refused), the session is consumed:

1. Require EUID root **before receiving socket bytes**.
2. Refuse duplicate/closed Unix connections and any mutation of the
   independently chosen account, disk, peer, review or deadline.
3. Kernel-check `SO_PEERCRED` on **both** existing Unix
   `SOCK_SEQPACKET` channels against the **same exact peer identity**.
   The client cannot pick its own expected PID/UID/GID.
4. Invoke the one-shot local preflight handler: separately trusted
   local consent followed by root-side disk attestation and its existing
   strict read-only JSON protocol.
5. Recheck current boot ID, trusted context and deadline. Require
   that the local session was actually consumed by the gate.
6. Construct a fresh **root-selected** strict preflight request
   entirely from trusted in-process state, not client-provided
   values; call PR #40's read-only physical preview. This
   independently re-probes current disk, mount/swap ancestry, live
   media and a held **O_RDONLY** block-device descriptor.
7. Check the manifest against the exact reviewed disk's
   `maj:min`, boot ID, review digest, username and hostname.
   Require the known GPT/1-GiB EFI/VFAT/LUKS2/Btrfs layout and
   the exact eight non-executable phase descriptions. Unknown
   manifest fields, injected command keys, wrong device, altered
   phases, checksum mismatch or a true write flag are refused.
8. Reverify the credential sender's pinned kernel identity and
   receive exactly TWO independently role-labelled, fully sealed
   Linux memfds through the PR #36 `SCM_RIGHTS` reader. No
   plaintext secret is transported as JSON, command-line args,
   environment data or a temporary filesystem path.
9. While the credential reader owns the mutable buffers, repeat
   the independent root-side physical preview and compare both
   full manifests and digests. Any hotplug, mount/partition,
   root/boot or disk-plan change fails closed.
10. Release/zero mutable LUKS and account buffers, close received
    FDs, then return a **read-only rehearsal report**.

The report includes only a non-secret plan digest, a fixed status and
`credential_transport_verified: true` on success. All four
flags (`write_operations_enabled`,
`destructive_disk_operations_enabled`,
`credential_writes_enabled`, `authorization_to_write`)
remain **false on success AND refusal**.

The manifest SHA-256 is only for drift detection. It is NOT a token,
signature, evidence of human presence, or disk-format authorization.

## Security constraints

- **No physical disk writes or writer code**: this library imports no
  disk formatter or installer and cannot invoke Disko, cryptsetup,
  a mount operation, password-hash staging, or `nixos-install`.
- **No new service or GUI bridge**: it cannot bind/listen on a socket,
  start a daemon, install systemd/polkit/sudo permissions or grant
  ordinary users access to the root-owned socket.
- **Strict one-shot use**: once an attempt begins, success or refusal
  prevents reusing that instance, even if a trusted local check fails.
- **Independent authorization required**: Linux `SO_PEERCRED`
  establishes a connected kernel peer identity, not operator consent
  or permission to erase; the production privilege delegation/seat
  policy still requires separate review.
- **Bounded transport**: the existing FD receiver enforces
  `MSG_CMSG_CLOEXEC`, valid role-specific sealed memfds, a timeout
  and short credential sizes, and zeroes its mutable buffers.
  It cannot guarantee Python immutable-string memory erasure.
- **Caller-owned socket lifecycle**: the library does not close the
  two supplied connected sockets. The future root invoker owns their
  creation, lifetime, permission policy and closure. It must close
  them even on refusal, including any queued unconsumed FDs.
- **No automatic retry or rollback**: if peer identity, consent,
  manifest or credentials fail, the report is redacted and the
  caller must begin a fresh separately approved session.

## Verification

A new fast no-ISO, unprivileged Nix check runs real Unix
socketpairs, Linux `SCM_RIGHTS` and sealed memfds while mocking only
physical disk access and effective root permission.

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-execution-rehearsal-tests
```

Tests cover full read-only success and separate consent, peer PID
mismatch, root refusal before socket reads, policy changes,
replay, expired/boot-swapped approval, forbidden `format-disk`
commands, failed local consent blocking secret reads, unsealed or
swapped FD roles, missing/late credentials, malicious manifest
commands/flags, incorrect disk layout, post-secret disk-plan drift,
mutable memory cleanup and absence of all execution entrypoints.

The existing PR #39 full real-root/nonroot adversarial QEMU check,
encrypted storage persistence, desktop/theme checks and broad
installer fixture tests remain in regular CI. Because this PR does
**not change the disposable QEMU installer, storage layout, boot
profile or full installation command path**, a separate full
encrypted-installation workflow rerun is not required.

## Next milestone: real execution requires further review

This rehearsal should inform the subsequent physical installation
design, but **must not be treated as the physical writer itself**.

A separately audited, narrowly permissioned formatter must:
- independently bind and recheck the held disk identity immediately
  before irreversible writes;
- prove fresh local human consent with defensible seat/session
  ownership, and a secure root invocation policy;
- accept only audited fixed storage operations and an immutable
  NixOS system closure—never arbitrary shell commands;
- consume and protect sealed secrets inside a hardened executor;
- stop on partial failures without automatic retries or unsafe
  rollback, and provide clear recovery guidance;
- pass adversarial disposable QEMU **destructive-path** integration
  before any production hardware installation is enabled.

**eduardOS — Forged in Neon.**
