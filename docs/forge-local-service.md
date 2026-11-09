# PR #37 — Trusted local read-only preflight and socket lifecycle

## Roadmap

PR #32 proved encrypted QEMU installation and user login. PR #33 defined root-only read-only disk attestation. PR #34 added one-shot QEMU installation phases. PRs #35 and #36 added role-separated sealed credential memory and kernel-authenticated Unix descriptor transfer.

This PR builds the **root-side one-shot consent/identity policy and private Unix socket lifecycle**, without enabling physical installation, a privileged service, a browser connection or a disk writer.

## Root-side trust policy

The future trusted controller must independently select an exact kernel PID / UID / GID, a fresh boot-specific disk review, and the installed username/hostname, and provide a separate authenticated LOCAL interactive confirmation callback. The policy never derives allowed identity or local approval from a socket request.

The new TrustedIntent deep-copies and fingerprints its disk review, verifies stable by-id identity and account settings, expires within 120 seconds, and is consumed on the FIRST attempt, including refusals.

The one-shot handler executes these gates:

1. Require effective UID 0.
2. Compare kernel SO_PEERCRED against the independently trusted PID / UID / GID.
3. Require the exact current Linux boot ID.
4. BEFORE reading request bytes, demand an exact ERASE + stable disk identifier response from the trusted local consent source. Check boot and expiry again after consent.
5. Receive just one bounded Unix SOCK_SEQPACKET JSON request, refusing all passed file descriptors, truncation, unknown fields and unexpected operation names.
6. Require the request to match the independently root-selected review, boot, username and hostname.
7. Invoke the existing read-only privileged disk preflight, which independently checks hardware, mount/swap ancestry and the stable disk alias.
8. Return a bounded response with all disk-write permissions FALSE; refusal replies are redacted.

There is no account password or LUKS secret transport on this channel. The sealed-FD IPC from PR #36 remains deliberately separate.

### Consent limitations

The library defines a mandatory local callback but does NOT implement a production human-presence check. In tests a simulated callback approves a known public fixture; production must use an independently authenticated local TTY/seat and must NEVER auto-return the expected phrase or forward it from the client socket. Matching SO_PEERCRED proves a connecting identity, not human consent. This is still not authorization to erase a disk.

## Root-only socket path policy

The optional root_listener library uses the fixed path:

/run/eduardos/forge-preflight.sock

The directory must already exist with exact mode 0700, owner root, and must not be a symlink. The Unix socket must be root-owned and mode 0600. It will never overwrite a pre-existing socket, file or symlink; cleanup removes only the exact inode it created, protecting replaced paths.

**No runnable service, systemd unit, polkit rule, root daemon or socket activation is added in this PR.** Only a library API exists, and ordinary non-root GUI clients cannot connect to the root-only path. Access policy for an interactive GUI requires a separately reviewed privilege boundary.

## Tests

The new forge-local-service-tests check uses ephemeral unprivileged Linux sockets and directories and mocks the physical-disk preflight. It checks peer mismatches, review/user/disk swaps, stale boot, expiry, independent consent, replay refusal, oversized requests, ancillary FD cleanup, non-root refusal, parent and socket permissions, symlink rejection and safe inode-specific socket cleanup.

Fast CI command:

    nix build --no-link -L .#checks.x86_64-linux.forge-local-service-tests

No ISO build, root privileges, disk formatting or real installed-system changes are required. The separate full encrypted-installation workflow is not needed because the QEMU executor and boot path are unchanged.

## Next after PR #37

Design and independently audit real local human-presence authentication, trusted service deployment/permissions, process lifecycle and resource limits. Perform root/non-root adversarial VM tests before connecting a narrowly privileged physical writer or the graphical install flow.

**eduardOS — Forged in Neon.**
