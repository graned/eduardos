# PR #45 — Disposable-QEMU child cancellation

**eduardOS — Forged in Neon** | Alpha 0.2 → Alpha 2.0

## Scope

The existing guarded QEMU-only executor used blocking `subprocess.run`
for Disko and nixos-install. A SIGTERM delivered to the Python supervisor
could leave a child formatting or installing after the supervisor exited.
This PR gives those *two existing, fixed* child processes their own
process groups and supervises them while preserving their allowlisted argv.

- `forge_lab_child.run_child` runs one argv array without a shell, with
  stdin closed and a separate session/process group.
- During the child wait, SIGINT/SIGTERM turn into a cancellation exception.
  Cleanup sends SIGKILL to the child process group and reaps the leader
  before restoring the original signal handlers.
- Nonzero exit is an error, never an automatic retry.
- The existing `InstallationTransaction` emits terminal halted status.
- The **PR #44 same-boot marker is retained** after interruption; it
  continues to refuse a second disposable installation attempt.
- AST command-policy tests still inspect the exact runner arguments,
  including the location of both supervised calls.
- A harmless Linux process test sends SIGTERM to the supervisor and
  checks that its running child stops. No block devices are opened.

## Limitations

SIGKILL, sudden VM power-off, kernel crashes and host shutdown cannot
be intercepted. A child could already have written partial GPT or LUKS
metadata before termination. There is **no rollback, automatic retry,
marker reset, disk cleanup or guarantee of pristine storage**.

This is exclusively for the pre-existing, root-gated, disposable-QEMU
`/dev/vda` lab. It does not create any new physical disk writer, IPC
service, privileged GUI operation or arbitrary command interface.

## CI

Fast isolated child tests:
```sh
nix build --no-link -L .#checks.x86_64-linux.forge-lab-child-tests
```

The changed installer runner triggers the *separate* full-install
workflow. **Do not merge** unless the regular integration checks, the
full Disko/OVMF/PAM installed login test and the real partial-GPT
failure/retry-refusal test all pass on the PR head.

## Follow-up

Separate PR: actual signal interruption and hotplug fault injection in
disposable QEMU, including interrupted child failure reports and
manual re-attestation. A production physical execution service still
requires independent authorization and a durable recovery journal.
