# Forge Installer — authorization and secret-input rehearsal (PR #24)

**Status: pre-execution UX and protocol only. Not a privileged installer.**

This PR adds a short-lived, single-use local authorization session to the
existing read-only Forge disk review. It is deliberately **not** connected
to the graphical HTTP server or the destructive QEMU lab executor. This
means there is still no route to wipe physical disks from the installer.

## Local flow

1. Capture a review for a physically blank disk using `forge-disk-review`.
2. On the *same boot session*, use `forge-authorization` to rehearse
   creation of the user/host and the explicit disk-erasure confirmation.
3. The tool re-reads the hardware using the disk identity gate from PR #23.
4. Type the full phrase `ERASE /dev/disk/by-id/<selected-id>`.
5. The tool returns a **read-only** acknowledgement. It cannot format,
   mount, install, elevate privileges or release any capability.

Run on Linux x86_64 with Nix (not the current Alpha 0.1 ISO):

```sh
nix run .#forge-disk-review -- --capture /dev/disk/by-id/EXAMPLE > review.json
nix run .#forge-authorization -- \
  --review review.json --username eduardo --hostname eduardos \
  --check-credentials
```

The optional `--check-credentials` validates one LUKS passphrase pair and
one account password pair via `getpass` on a real terminal. It checks
minimum length (12 characters), confirmation matching, and rejects
newline/NUL/control-line-break characters. Passwords are not printed,
returned, sent to the browser, written to the Nix store, persisted to the
review JSON, or forwarded to a privileged helper. Without
`--check-credentials`, no passwords are requested.

**Important secret-handling limitation:** Python `str` objects are
immutable and can remain in process memory until garbage collection or
process exit. This is a UX validation prototype, **not** secure credential
storage, zeroization or handoff. Actual production installation will need
an appropriately isolated credential helper and a reviewed FD-only / in-
memory transport, with no secrets in shell arguments, environment
variables, logs or world-readable files.

## Authorization rules

- Username: lowercase Linux-style unprivileged identifier, excluding
  reserved internal accounts (including `forge`, `root`, `greeter`).
- Hostname: restricted lowercase single DNS label.
- Two-minute process-local expiration after creating a session.
- Fresh random in-memory nonce; single attempt consumes session, even
  if the confirmation is wrong.
- Exact, full `ERASE /dev/disk/by-id/...` confirmation phrase.
- Fresh revalidation of the complete PR #23 disk review and boot session.
- Explicit `write_operations_enabled: false` in all successful output.

The ephemeral token is not an operating-system access-control
mechanism or an authorization capability. A privileged executor must
**independently** revalidate ownership, identifiers, filesystem ancestry
including root/boot, mount state, and user consent immediately before
writing, within its own restricted trust boundary.

An intentionally blank disk is the only supported current review case.
The workflow does not support erasing existing installations, dual boot,
or migration.

## No ISO build / tests

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-authorization-tests
```

Fast CI tests cover password policies, reserved usernames, exact disk
phrases, nonce errors, stale/changed hardware, expiry, repeated
authorization, TTY restrictions and the absence of writer methods.
These tests use mocked hardware. No disks are opened.

## Remaining blockers to an installable Alpha 0.2

- A small, independently privileged helper with strict stable-disk
  and current-system ancestry protection.
- Root/boot physical parent verification across dm-crypt/RAID/LVM.
- Secure user password creation and LUKS credential handoff without
  exposing secrets in the store or logs.
- Actual NixOS system/user profile for installed machines rather than
  the test-lab profile.
- Disposable-VM execution tests and a manual Alpha 0.2 release ISO.

No part of PR #24 should be interpreted as approval to run Disko on a
real machine.
