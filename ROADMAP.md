# eduardOS — Forged in Neon

## Roadmap: Alpha 0.2 → Alpha 2.0

This file is the **living development baseline** for eduardOS.
It records *verified* milestones separately from planned engineering
work. We do not equate the number of merged PRs with release readiness.
Update this file when completing a milestone or changing its scope.

**Release goal:** Alpha 2.0.  
**Next milestone:** Alpha 0.2 — a genuinely installable, encrypted
eduardOS ISO that we can validate safely on disposable QEMU disks before
carefully testing a real computer.

### Completed foundations

- [x] NixOS-flake-based eduardOS development and VM environment
- [x] Hyprland/Wayland desktop, Forge themes, Catppuccin/Ghostty and
  **Forged in Neon** Aztec-inspired identity
- [x] Alpha 0.1 live environment and bootable ISO profile
- [x] UEFI/GPT, LUKS2 and Btrfs layout, six mountpoints, cold-boot
  encrypted persistence
- [x] Disposable-QEMU installation of the actual system, encrypted
  reboot, real installed user and PAM login (through PR #32)
- [x] Privileged **read-only** stable-disk review and protected
  boot/mount/swap ancestry validation (PR #33)
- [x] QEMU-only one-shot fail-closed installation transaction (PR #34)
- [x] Separate sealed LUKS/account secret FDs (PR #35)
- [x] Linux `SO_PEERCRED` and `SCM_RIGHTS` local transport (PR #36)
- [x] Root-side read-only consent policy, protected local socket
  lifecycle, explicit physical-console approval (PRs #37–#38)
- [x] Adversarial real-root/non-root QEMU security tests (PR #39)
- [x] Double-audited, non-executable physical installation manifest
  (PR #40)

### Alpha 0.2 — first installable ISO

**Release exit criteria:** Boot a production ISO, pick an eligible
disk with a stable device identity, explicitly confirm destruction,
configure encryption and a real account, install and boot successfully,
then validate recovery from representative failures.

- [x] Integrate local consent, read-only disk review and two sealed
  credentials into a single bounded **non-destructive rehearsal**
  (PR #41 merged).
- [x] Specify and CI-enforce the existing disposable QEMU Disko /
  NixOS command allowlist and irreversible-boundary read-only
  mount/swap policy (PR #42 merged).
- [ ] Integrate that allowlist with the **actual guarded disposable-QEMU**
  formatter and repeat read-only kernel mount/swap and held-device
  identity checks immediately before Disko. Require the **full encrypted
  installation, cold-boot and login** workflow (**PR #43 in review**).
- [ ] Design and implement an *independently authorized*, narrowly
  allowlisted physical execution boundary. It must recheck the exact
  selected disk at the irreversible format boundary, never rely
  on a manifest digest as authority, and never accept arbitrary shell
  commands or writable devices supplied by a browser.
- [ ] Consume LUKS/account secrets securely in the trusted executor,
  without writing plaintext to command arguments, environment,
  the Nix store or unencrypted temporary files.
- [ ] Prove failure, cancellation, unexpected mounts, changed boot,
  hotplug, partial-format and recovery handling in **destructive
  disposable-QEMU integration tests**.
- [ ] Connect the Forge graphical installer to the audited root
  service without granting the GUI unrestricted root access.
- [ ] Add clear progress, refusal, cancellation and recovery UX.
- [ ] Build the actual installable ISO and validate installation,
  encrypted restart, first-login and repeated cold boot.
- [ ] Validate a narrowly selected set of real UEFI computers,
  confirming disk safety and hardware support before publishing.

**Release guard:** A read-only security test passing is NOT permission
to erase physical disks. Physical writes stay disabled until the
destructive-path safeguards and VM tests have been reviewed.

### Alpha 0.3 — reliability & recovery

- [ ] Recovery boot path and documented encrypted repair flow
- [ ] Update/rollback workflow, Nix generations and snapshot policies
- [ ] Broader Wi-Fi, storage, graphics and laptop hardware validation
- [ ] Diagnostics for failed boots, mounts, networking and upgrades
- [ ] Migration and configuration compatibility tests

### Alpha 1.x — complete daily-driver experience

- [ ] Reliable installer upgrades and release-channel lifecycle
- [ ] Polished power management, networking and peripheral support
- [ ] Desktop accessibility and keyboard/multi-monitor validation
- [ ] User-facing configuration and onboarding experience
- [ ] Signed releases, provenance and reproducibility validation
- [ ] Broader community documentation and hardware test matrix

### Alpha 2.0 — project goal

**Exit criteria:** A cohesive, reproducible and securely updatable
eduardOS that can be repeatedly installed, operated, upgraded and
recovered on a documented set of supported machines, with its
Neon/Aztec desktop identity preserved across releases.

- [ ] Strong multi-version upgrade, rollback and backup guarantees
- [ ] Explicitly supported hardware matrix and compatibility policy
- [ ] Automated install/boot/upgrade/recovery acceptance tests
- [ ] Security audit of privileged installer and update boundaries
- [ ] Reproducible release artifacts, signing and published checksums
- [ ] Completed installation, recovery and contributor documentation

## Pull-request discipline

- One independently reviewable scope per PR. **The user merges**.
- No merge while required CI is red, cancelled or pending.
- Run complete encrypted installation when the disk writer,
  installed profile, boot path or credential staging changes.
- Run relevant real-root/non-root adversarial VM tests for new
  authentication and privilege boundaries.
- Keep mock-only, read-only and destructive tests clearly separated.
- Prioritize the next release's acceptance criteria over accumulating
  unused infrastructure or declaring premature release readiness.

**Next after PR #43:** expand disposable-QEMU destructive-path
failure/cancellation/recovery cases, then independently review a
privilege-separated physical execution service. None of the QEMU
lab's `/dev/vda` authority or public fixture credentials may be
repurposed for real-hardware installation.

⚡ **eduardOS — Forged in Neon.**
