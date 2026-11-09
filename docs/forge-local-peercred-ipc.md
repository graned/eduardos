# PR #36 — Kernel-authenticated local credential transport (NOT a root service)

## Why this matters

PR #32 proved real encrypted installation and login in disposable QEMU.
PR #33 introduced **read-only** root-side target attestation.
PR #34 established one-shot, fail-closed QEMU transaction sequencing.
PR #35 added separate, sealed Linux memfds for LUKS and account secrets.

PR #36 tests the missing **local peer-identity and descriptor-transfer
boundary** using Linux Unix-domain sockets. It deliberately creates **no
root daemon**, socket listener, polkit action, privileged CLI, browser API,
physical-disk writer or installed-system change. Production activation
needs separate security review and explicit permission policy.

## Transport

The new library `installer/forge_local_ipc.py` accepts only an
**already-connected**, local `AF_UNIX/SOCK_SEQPACKET` socket supplied by
a trusted caller. The library does not bind any path or start a service.

Each one-shot sender and receiver must be constructed with an explicit
trusted `PeerIdentity(pid, uid, gid)`, obtained independently of the
remote socket's payload. Both endpoints use Linux `SO_PEERCRED` to
verify the **kernel-reported** peer identity before sending or accepting
credentials. No caller-provided JSON `uid`, username, nonce, hostname,
socket pathname or memfd name can substitute for this comparison.

The sender must verify the receiving **server** identity before passing
secrets (to avoid disclosing secrets to an impersonator). The receiving
side must verify the **client** identity before accepting descriptors.
An allowlist mismatch consumes the endpoint instance and refuses.

An exact fixed-length `EDOS-CREDENTIAL-FDS-V1` marker is the **only
message content**. No secret strings, account passwords, LUKS keys,
hashes, disk IDs, plan reviews or commands are serialized on the
socket. The two credentials are transferred using one
`sendmsg(SCM_RIGHTS)` ancillary message in a deterministic order.

The receiver calls `recvmsg(..., MSG_CMSG_CLOEXEC)` and strictly
requires exactly two returned FDs, no unexpected ancillary data, no
truncated packet/ancillary data and an exact protocol marker. It
**closes every received descriptor** even if parsing, peer checks,
the application callback or one of the credentials fails.
Each received FD must pass the existing PR #35 role, memfd-type,
size, immutable-seal and close-on-exec checks.

The receiver yields temporary mutable credential buffers through the
existing `OneShotCredentialReader`. They are zeroed when its context
exits. Both sender and receiver objects consume their **one and only**
attempt even on failure; neither provides retry or resumable authority.
A short, fixed receive/send timeout avoids indefinite blocked reads.

## Important security limitations

**This is transport authentication, not permission to perform an
installation.** Linux `SO_PEERCRED` reports the peer credentials pinned
at connection time. It does not prove recent human consent, cannot
prevent an already-authorized peer from forwarding socket descriptors,
and cannot prove which process originally created a memfd. A role label
and file seals are not cryptographic sender identity.

In particular:

- The **trusted policy** that chooses allowed PID/UID/GID and binds
  the UI session to a specific reviewed disk and fresh local consent
  is **not implemented in this PR**.
- No socket path, listener, root daemon, permission escalation, polkit
  rule or GUI-to-root interaction is configured.
- The existing privileged `forge-privileged-protocol` remains strictly
  read-only; these sealed credentials cannot be sent to it.
- No physical device write, QEMU install call, cryptsetup action or
  `nixos-install` call is available in this transport.
- Original sender-held memfds are not revoked by the receiver: the
  sender remains responsible for closing its own copies.
- Python may keep immutable secret strings/copies in memory beyond
  the lifetime of the zeroed mutable buffers. A hardened Rust consumer
  could provide stronger memory control in future work.
- Socket file permissions, allowed Linux user groups, privileged
  caller lifecycle, consent/replay binding, lock-down/sandboxing and
  denial-of-service handling all need a separate reviewed service
  design before production use.

## Checks

The new `forge-local-ipc-tests` fast Nix check uses real Linux
`SO_PEERCRED`, `SCM_RIGHTS`, sealed memfds, Unix socketpairs and an
**unprivileged separate connecting process**. Tests cover:

- Exact successful dual credential transfer and buffer erasure.
- Sender **and receiver** refusals for wrong trusted PID/UID/GID.
- Rejection of stream sockets (no ambiguous byte-stream framing).
- Invalid/missing/extra/truncated packet or ancillary FD data.
- Wrong role, duplicate and invalid sealed credential FDs.
- Descriptor leak checks across malformed frames and callback failures.
- One-shot refusal on second invocation.
- Real kernel PID reporting from a separately connecting local process.
- No privileged installer, socket-binding or disk-formatting entrypoint.

Run only the quick tests:

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-local-ipc-tests
nix build --no-link -L .#checks.x86_64-linux.forge-secret-handoff-tests
```

No ISO, root privileges, disks or full installation VM is required
for this isolated IPC library change. Regular PR system integration
checks remain enabled.

## Roadmap next

**PR #37** should define the separately reviewed local service
identity/permission model, authenticated user presence, fresh
disk/boot/consent binding, a root-owned socket lifecycle, and a
non-destructive end-to-end service test. Only after that review and
more QEMU attack/failure testing should any physical writer be designed.

**eduardOS — Forged in Neon.**
