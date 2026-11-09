# PR #39 — Adversarial real-kernel installer boundary testing

## Roadmap

eduardOS Alpha 0.2 must prove its installation trust boundary in a
disposable virtual machine before we consider implementing the
privileged physical disk writer. The long-term milestone remains
**eduardOS Alpha 2.0**.

PRs #33–#38 introduced read-only root-side disk attestation, a one-shot
local consent session, sealed credential FDs, peer-verified Unix socket
transport, a root-owned socket lifecycle and a manually invoked
physical-VT prompt. PR #39 provides a distinct integration test that
exercises **real Linux process and filesystem permissions** rather
than relying only on mocks and fixture-level checks.

## What is real in this test

The `forge-local-adversarial` NixOS test boots its own **minimal QEMU
guest** and runs the security scenario suite as real root. The suite
creates separate forked processes, including a process that permanently
drops its UID/GID to 65534. It uses:

- Linux `SO_PEERCRED` to validate actual sender PID/UID/GID at accept.
- Linux `pidfd_open` and `poll` to detect dead or recycled clients.
- A real root-owned `/run/eduardos` directory at mode 0700 and a
  transient `forge-preflight.sock` Unix socket at mode 0600.
- Real `AF_UNIX/SOCK_SEQPACKET` messages, truncation, connection
  closure and `SCM_RIGHTS` descriptor passing.
- Real Linux sealed anonymous memfds for the credential-injection
  negative test.
- Real one-shot lifecycle and exit cleanup, not simply mocked
  `socket.accept` / `socket.recvmsg`.

The test runs a separately forked **root client** for approved
read-only requests. That client is kept alive through a pipe until the
root service finishes its post-request pidfd check.

## Adversarial scenarios

The VM checks:

1. Genuine root peer accepted for ONE **read-only** attestation.
2. Non-root user denied by actual kernel directory/socket permissions.
3. Different root PID cannot impersonate the pinned authorized process
   even when both have UID/GID 0.
4. Second request on the same connection cannot create another
   preflight or acquire a reusable authorization.
5. Unsupported destructive operations (including `format-disk`) denied.
6. Disk by-id identity, review digest and account changes refused.
7. Secrets smuggled in request JSON denied.
8. Two sealed credential FDs passed to the read-only request channel
   refused and closed without leaks.
9. Oversized/truncated requests refused.
10. Silent socket peer times out and gets a redacted denial.
11. Rejected local consent cannot be bypassed by a valid root request.
12. A dead client process cannot start a session with an old PID.
13. Pseudo-terminals and non-VT device paths cannot authorize a
    local physical-console confirmation.

The test asserts that failure responses and success responses grant no
write permission and that the root-owned socket does not survive the
one-shot invocation.

## The intentional safety boundary

**No disk can be formatted by this test.** The test VM contains no
disposable target disk to be formatted. The physical disk capture
is replaced with a purely synthetic disk review, and the root disk
attestation backend is explicitly mocked to return a **read-only**
fixture. Both the selected stable disk ID and any user credentials in
the test are public disposable fixture strings.

The local physical-console confirmation callback is also simulated
for the allowed-root branch: automated QEMU CI has no physically
present human to type on its foreground virtual console. Independent
tests and real non-console denial cases still enforce the console
restriction. This VM test does not claim to validate a positive
human-presence approval on real hardware.

This PR does not introduce a daemon, default listener, systemd
activation, polkit privilege grant, browser bridge, GUI installation,
cryptsetup, Disko, or a physical-disk writer. Existing installed
profiles, ISO boot, encrypted storage and the QEMU lab installer
remain unchanged.

## Verification and CI cost

Run just the adversarial VM:

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-local-adversarial
```

PR CI runs this in a **separate parallel KVM job** with a small NixOS
guest. This keeps the critical path of the existing fast flake/theme
checks unaffected and avoids building another full encrypted
installation ISO.

Because no destructive installer code changes, running the separate
full encrypted install workflow is not required for this PR.

## Next milestone

PR #40 should design an **independently reviewed physical execution
boundary**. It must bind the open disk descriptor to an exact
pre-verified device and re-audit mounts, live media, user consent,
failure recovery and credential handling. All destructive actions
must remain disabled until that implementation passes further
disposable QEMU tests and security review.

**eduardOS — Forged in Neon.**
