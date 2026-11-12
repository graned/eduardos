# eduardOS — FROZEN Alpha 0.2 delivery roadmap

**Frozen on:** 2026-11-12  
**Owner:** Project conductor (user)  
**Release target:** Alpha 0.2 — Forged in Darkness  
**Scope changes:** Only after explicit user approval. No automatic new milestones.

> The number of merged PRs is **not** evidence of release completion.
> Alpha 0.2 has **exactly three remaining delivery milestones**.
> Bugs, tests and security fixes are implementation work under these milestones,
> not new roadmap items.

## Baseline — already implemented

- NixOS desktop environment, Forge Eclipse appearance and developer-tool foundation.
- Graphical Forge preview: hardware, candidate disks, non-secret configuration and capability status.
- Independently guarded disposable-QEMU installer using Disko, encrypted Btrfs, real user credential staging and NixOS installation.
- Existing disposable-QEMU acceptance has exercised encrypted boot, account authentication, persistence and a second cold boot.
- Read-only physical disk review and recovery safety groundwork; **physical installation remains disabled**.

**Not yet true:** Forge GUI cannot perform an installation. Running the GUI preview
inside the same QEMU guest as a separately invoked lab installer is not
GUI-driven installation.

## Remaining milestones — fixed

### 1. Connect Forge GUI to an authorized installer

**Goal:** A person can initiate a separately authorized, VM-only installer
from Forge, using the existing lab execution implementation rather than
another parallel safety framework.

**Acceptance criteria:**
- GUI presents the selected disposable VM target and obtains explicit,
  independent local authorization at the privileged execution boundary.
- Account and disk-unlock credentials are delivered through a trusted
  mechanism without plaintext in process arguments, environment, Nix store,
  HTTP responses or logs.
- Only the existing disposable-QEMU execution path can run; the production
  GUI must not expose a general physical-disk writer.
- GUI reports real bounded phase events, terminal success/failure,
  cancellation and manual-recovery-required state; no automatic destructive retry.
- Hostile/stale requests and changed disk identity fail closed.

**Done means:** A guarded lab install can be initiated from the GUI
with truthful progress and terminal outcome. Not merely an API preview.

### 2. Prove end-to-end GUI installation on a fresh VM

**Goal:** Prove the entire user-facing flow, not just the lab CLI.

**Acceptance criteria:**
- Boot the release-candidate environment in disposable QEMU with a fresh disk.
- Choose the target, configure a user and start installation **through Forge**.
- Confirm real Disko format + NixOS install, encrypted UEFI boot,
  correct user login, and a second cold boot retaining home/persistent data.
- Exercise interruption/partial-format refusal and no automatic retry.
- The full applicable QEMU CI suite is green; no mocked formatter in the
  success-path acceptance test.

**Done means:** A real GUI-driven VM installation survives cold boot and recovery tests.

### 3. Package, verify and publish the Alpha 0.2 ISO

**Goal:** Deliver one usable, reproducible VM-qualified alpha image.

**Acceptance criteria:**
- ISO boots into the intended eduardOS desktop, Forge experience and
  developer tools with the Eclipse default branding.
- The **ISO itself** passes the supported disposable-QEMU GUI-install flow
  and encrypted reboot acceptance (not only a separate test harness closure).
- Checksum, exact supported VM configuration, installation instructions,
  known limitations and recovery cautions are published.
- Required CI is green; user reviews the release evidence and explicitly
  approves publishing.

**Done means:** Downloadable Alpha 0.2 artifact plus verification evidence.

## Explicit exclusions — NOT Alpha 0.2 blockers

- General-purpose physical-hardware installation and a claim of safety for arbitrary user disks.
- Broad hardware matrix, driver/peripheral tuning and daily-driver guarantees.
- New themes, redesigned UI, advanced snapshot/rollback products.
- Extra CLI commands, container engines, project templates or unrelated applications.
- Automatic retry or recovery of partially formatted disks.

Physical hardware installation must remain disabled until separately
reviewed and qualified. These exclusions can be planned for later releases
without redefining Alpha 0.2.

## Implementation discipline

1. Work **only** on the three remaining milestones, in order.
2. Merge existing PRs #89 and #90 only if applicable CI passes; they are
   supporting tests, not new milestones or release blockers by themselves.
3. Prefer modifying and integrating existing Forge components. No new
   abstraction or policy PR unless it is necessary to unblock a milestone.
4. An actual defect/security failure is fixed **within** its parent milestone;
   it does not increase the milestone count.
5. Tests needed to establish an acceptance criterion are part of that
   milestone, not a new feature.
6. Keep ISO builds at checkpoints instead of on every small PR, but run
   destructive QEMU tests for changes to executable installer behavior.
7. Do not merge automatically: user decides after review and green CI.
8. Report progress as **0/3, 1/3, 2/3 or 3/3**, and provide the evidence;
   never equate PR count with completion.
9. The roadmap can be amended **only by explicit user approval**.

## Later releases (non-binding, outside this scope)

- **Alpha 0.3+:** separately audited physical-hardware installation,
  supported hardware qualifications and recovery/rollback improvements.
- **Alpha 1.x:** broader daily-driver reliability and upgrade workflows.
- **Alpha 2.0:** documented robust installation, update, rollback and
  recovery on an explicitly supported hardware matrix.

---

⚡ **eduardOS — Forged in Darkness.**
