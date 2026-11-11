# eduardOS Alpha 0.2 — live delivery gates

**Last reconciled:** November 11, 2026. **Next release:** Alpha 0.2. **Ultimate goal:** Alpha 2.0.

This document is the **current execution baseline**. Earlier numbered planning slots no
longer correspond to the actual GitHub PR numbers. A release is not complete
just because many PRs have merged. Future PR numbers are not reserved.

## Current GitHub checkpoint

These changes are already incorporated on the default branch:

| Actual PR | Work landed | Qualification remaining |
| --- | --- | --- |
| #61 | Developer project initialization templates | Preview, overwrite and Nix packaging checks |
| #62 | Forge accessible disk navigation | Browser/keyboard testing |
| #63 | Offline Nix environment preview | No automatic Nix evaluation |
| #64 | Forge HTTP safety regression suite | Security CI coverage |
| #65 | Offline Compose discovery | Manifest ambiguity |
| #66 | Strict read-only disk preview replies | Browser race testing |
| #67 | Opt-in Docker/Podman Compose up/down/status | Real-engine/cancellation tests |
| #68 | Non-secret configuration schema | Nix schema parity |
| #69 | Same-user PID resource snapshots | Project and cgroup stats incomplete |
| #70 | Forge non-secret configuration wizard | Browser end-to-end testing |
| #71 | Redacted developer context | No project data or network transfers |
| #72 | Stale draft invalidation | Browser delayed-response tests |

**Open as of reconciliation:** #73 (opt-in clean Neovim workspace launch) and
#74 (persistent installation attempt marker primitive). Both require CI and
user review. Neither is presumed merged.

## Release-critical workstreams

### Developer-first CLI

- [x] Rust diagnostics, read-only manifest inspection and project templates
- [x] Nix/Compose discovery and explicitly selected Docker/Podman actions
- [x] Same-user PID resource snapshot and redacted project ecosystem context
- [ ] Review/merge workspace launcher (#73)
- [ ] Deliver expressly approved Nix development shell execution OR explicitly
      defer it. The current Nix command only previews; it does not enter a shell
- [ ] Validate real Docker/Podman execution, cancellation, failure propagation
      and consent on untrusted Compose manifests
- [ ] Project/cgroup resource statistics remain more limited than the current
      single-PID snapshot
- [ ] Correct CLI-wide read-only descriptions: some opt-in commands now create
      files or execute containers, although they never install an OS
- [ ] Rust tests, Nix package, live and installed integration, documentation

### Installer trust boundary — not yet physically writable

**Current boundary:** the Forge GUI only previews hardware and validates a
non-secret configuration draft. Root physical attestation is read-only. The
existing guarded destructive formatter is locked to disposable QEMU /dev/vda.
None of those components grants writes to physical hardware.

- [x] Stable-disk capture, read-only root ancestry checks and QEMU lab install
- [ ] Reattest exact held block FD, stable alias, hardware identity, current
      boot, mount and swap state at the future irreversible boundary
- [ ] Review/merge persistent attempt primitive (#74). Integrate only after
      verifying nonvolatile root-controlled backing storage, locking, reboot
      behavior, crash consistency and an audited manual recovery policy
- [ ] Review independently authorized physical executor with a closed
      allowlist of exact immutable Disko/Nix commands, no shell or browser-
      supplied writable path and no manifest digest accepted as permission
- [ ] Trusted LUKS and account-secret delivery with sealed descriptors;
      no plaintext in argv, environment, Nix store, logs or unencrypted files
- [ ] Adversarial changes to mounts/swap, hotplug, alias identity, boot,
      credentials, power loss and partial formatting in disposable QEMU
- [ ] Keep physical writes disabled until independent security review

### Forge GUI and execution integration

- [x] Forge Eclipse preview with keyboard disk selection and safer stale
      response handling
- [x] Non-secret hostname, username and disk-identifier validation
- [ ] Narrow, versioned, local unprivileged-GUI to audited-root protocol
- [ ] Independent consent and secrets, clear phases, safe cancellation,
      terminal failure, recovery instructions and no automatic destructive retry
- [ ] Browser tests for spoofing, malformed requests, delayed replies and
      stale selected disk/configuration state

### ISO and release gates

- [ ] Actual GUI-to-executor install of the same system in disposable QEMU;
      encrypted cold boot, real user login and repeated reboot acceptance
- [ ] Integrated installable ISO with final Rust CLI, GUI and trusted service
- [ ] Build ISO at checkpoints, not on every small PR; always run destructive
      QEMU integration for changes to writer, mounted target or credentials
- [ ] Controlled UEFI hardware qualification with backups and test matrix
- [ ] Checksums/provenance, installation/recovery docs and known limitations
- [ ] All required CI green, evidence reviewed, user-approved Alpha 0.2 release

## Safe execution order

1. Finish reattestation, persistent state and adversarial checks, separately.
2. Audit the exact privileged executor boundary and secret transport.
3. Exercise destructive operations only in disposable QEMU until proven safe.
4. Connect the non-root GUI to the versioned independently authorized service.
5. Build and verify installable ISO; carefully qualify supported real hardware.
6. Publish Alpha 0.2 only after all release gates pass.

Parallel PRs should own separate files or well-defined interfaces. Every
PR requires review and green applicable CI, and **the user merges each PR**.

## Later milestones

**Alpha 0.3:** recovery, Nix generations and rollback, snapshots, update
workflow and broader hardware coverage.

**Alpha 1.x:** daily-driver reliability, power/networking/peripheral polish,
configuration migration and release channel lifecycle.

**Alpha 2.0:** reproducible installation, upgrade, rollback and recovery
guarantees for a documented supported hardware matrix.

⚡ eduardOS — Forged in Darkness.
