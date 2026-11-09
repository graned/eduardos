# PR #38 — Root/physical-console authenticated read-only preflight

## Milestone

Previous PRs #32–#37 established encrypted QEMU installation, root-side
read-only disk attestation, sealed credentials, kernel-checked Unix
transport, root-owned socket lifecycle, and a one-shot consent policy.

PR #38 closes two implementation gaps: **an actual local operator
challenge** and **an opt-in, executable, one-shot preflight launcher**.
It advances the Alpha 0.2 installer track toward Alpha 2.0 without
introducing a physical-disk writer.

## Safety boundary

The optional Nix package `forge-console-preflight` is only callable
on demand. It is NOT installed in the live ISO, enabled by systemd,
exposed to the Forge GUI, or configured with sudo/polkit authorization.
It never invokes Disko, cryptsetup, `nixos-install`, the QEMU lab
executor, or the sealed account/LUKS credential receiver.

**The only operation remains read-only disk attestation.** This is not
a disk erasure authorization, even though the operator types an
`ERASE /dev/disk/by-id/...` phrase inherited from the review contract.

### Separate trusted selection

The root operator explicitly supplies a stable by-id disk identifier,
installed user/hostname settings, the PID of a separately trusted root
client, and a physical virtual console such as `/dev/tty2`.

The launcher independently captures the latest disk identity/boot
snapshot from the kernel. It does not accept a review or identity
assertion from a socket packet as its root-side policy.

The root-selected client PID is held with Linux `pidfd_open`. A client
that exits before or during the request is rejected; the pidfd is
closed on every path. The existing session requires that the peer
present **exactly** that kernel-reported PID, UID 0 and GID 0 via
`SO_PEERCRED`. Only a root-owned, mode-0600 Unix socket inside the
root-owned mode-0700 `/run/eduardos` directory may be used.

### Interactive local confirmation

The callback is now implemented by
`forge_console_consent.request_local_consent`:

- Requires root, an explicit `/dev/tty1` through `/dev/tty63`
  (not `/dev/pts`, a pseudo-terminal, SSH, redirected stdin or
  a browser input).
- Opens the virtual-console device with `O_NOFOLLOW` and checks
  its inode and kernel character-device major/minor.
- Uses the Linux `VT_GETSTATE` ioctl to prove that the exact
  requested virtual console is currently active.
- Requires the current process to be the console's foreground job
  via `tcgetpgrp`. A root process on a remote/other terminal cannot
  approve by merely opening the VT file.
- Displays the exact stable-disk challenge on that virtual console,
  reads a bounded 512-byte ASCII response with a 60-second deadline,
  and restores TTY settings on every exit path. Echo is disabled.
- Rechecks VT activity/foreground status when input completes.
- The existing root-side `TrustedIntent` validates the exact phrase,
  current boot ID, root-selected disk and account, and its own 120s
  one-shot expiration before allowing independent kernel disk review.

**Scope note:** This proves a foreground active kernel VT, not a
full logind/seat authorization, fingerprint, MFA, or a cryptographic
proof of human presence. A privileged root session can still act as
root. Such checks and a least-privilege GUI access policy require
separate security review and VM testing.

### One-shot command

The optional command is:

```sh
forge-console-preflight \
  --disk-id /dev/disk/by-id/<stable-disk-id> \
  --username <installed-user> \
  --hostname <installed-host> \
  --client-pid <trusted-root-client-pid> \
  --console /dev/tty2
```

This command is deliberately **not a complete two-process GUI flow**.
It expects a separately trusted root client to connect to the fixed
one-shot socket and send the strict `attest-target` JSON packet
matching the root-selected disk review. The client must already
exist, be root-owned, and match the pinned PID. The existing
`forge_local_service` checks that packet and performs another
read-only review. The listener accepts only one connection, then
closes and removes only its own socket inode.

The root-owned `/run/eduardos` directory must have been prepared by
a trusted operator before launching; the command refuses to create
permissions or change the socket policy automatically.

An inactive tty, an SSH/PTY session, wrong disk/username/host, stale
review, changed boot, failed local confirmation, expired session, or
exited client produces a refusal, without echoing user-controlled
request data or raw errors to stderr.

## Tests and CI

The new unprivileged fast check
`forge-console-preflight-tests` uses mocked Linux virtual-console
ioctls and TTY operations, fake root disk capture, pidfd lifecycle,
and existing one-shot socket session callables. It validates:

- Active VT number, Linux character device, root and foreground job.
- Explicit rejection of SSH/pseudo-terminals, inactive consoles,
  incorrect device identity, and non-root execution.
- Exact typed phrase, bounded response, timeout, TTY restoration and
  descriptor cleanup on both success and failure.
- Pinning an independently chosen root client PID via pidfd.
- No disk review or listener start after an invalid or exited client.
- One-shot listener shutdown and redacted CLI failures.

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-console-preflight-tests
```

Existing disk-review, encrypted-boot, sealed-FD, Unix peer identity
and desktop tests remain in regular CI. Since the QEMU destructive
installer, disk layout, installed user profile and boot path are
unchanged, the separate full encrypted installation workflow is
not required for this PR.

## Next security milestone

PR #39: adversarial root/non-root disposable VM tests for the *actual*
one-shot service with kernel VTs and a real peer process, plus hardening
of live ISO service/seat ownership and cancellation/timeout behavior.

Do not enable physical-disk writes until an independently audited,
narrowly privileged writer, secure credential use, and all safety and
recovery paths have been tested in disposable VMs.

**eduardOS — Forged in Neon.**
