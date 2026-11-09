# PR #44 — Terminal failure, partial-format recovery and no automatic retry

**eduardOS — Forged in Neon** | Alpha 0.2 → Alpha 2.0

## Why

PR #43 merged after the separate full encrypted installation workflow
passed: actual Disko formatting, LUKS2/Btrfs, OVMF cold boots, installed
user and PAM authentication.

The existing `InstallationTransaction` prevents retrying *the same
object*, but a second invocation of the lab executable in the same
boot could otherwise start a new transaction after the first
partially formatted its disposable disk. PR #44 closes that
**same-boot QEMU lab** gap and adds a real partial-write failure test.

This is a deliberately narrow recovery milestone. It does not implement
or activate a physical installer, disk repair, rollback, automatic
format retry, or arbitrary root command.

## Root-owned one-shot attempt marker

New module: `installer/forge_lab_attempt.py`.

The *existing* QEMU-only executable (root, QEMU/KVM DMI, test-only
marker, exact disposable `/dev/vda` path, held read-only block FD,
mount/swap ancestry and confirmation all remain mandatory) now:

1. Refuses an existing **format-started** marker before preparing its
   installation plan. Even a different process with the same confirmation
   cannot silently retry in that boot.
2. At the **last irreversible boundary**, after the fresh kernel
   mount/swap/boot/device-identity audit and immediately before Disko,
   atomically creates the constant marker:
   `/run/eduardos-qemu-format-attempted`.
3. Requires root, `O_CREAT|O_EXCL|O_NOFOLLOW`, exact owner root,
   a regular file and mode `0600`. A pre-existing file, directory
   or symlink always refuses. The marker contains only a fixed public
   protocol marker; no passwords, identities, disks or logs.
4. Persists the marker after **success and failure**, refusing another
   attempt during the *same QEMU boot* regardless of whether any later
   phase, user credential staging or NixOS installation succeeds.
5. Does **not** remove, rotate, reset or reuse the marker on failure.

A failure *before* that irreversible boundary need not create the
marker. The transaction still records `format-started` conservatively
before invoking the formatter callback, so a failure in the final
audit can appear as `halted-after-format-started` even when Disko
was never reached. This is intentional: the GUI must never infer
pristine storage from a generic error phase.

### Important limitation

The marker lives in `/run`, so it **disappears across a reboot**.
This is a *same-boot lab interlock*, **not a durable disk journal or
physical hardware authorization**. It cannot prove an empty disk is
safe, prevent a privileged human from deliberately bypassing it,
or provide crash-atomic persistence across power loss.

A production physical installer will require a separately designed
durable, fail-closed consent/execution record and manual
disk re-attestation after interruption. Never reuse this ephemeral
QEMU mechanism as proof that physical installation is safe.

## Read-only recovery status

`forge_lab_attempt.recovery_report()` classifies:

- `no-attempt-recorded`: no marker, but disk condition is **unknown**.
- `manual-recovery-required`: a root-owned marker exists; the QEMU
  target **may be partially formatted**.
- `untrusted-attempt-marker`: unexpected type/ownership; treat
  the attempt as unsafe and refuse to infer a clean state.

Every report sets disk writing, automatic retries and automatic
rollback to **false**. It has no disk writer, marker-clearing function,
subprocess entrypoint or executable recovery command.

After a failure, the safe operator workflow is to **stop**. Inspect
the disposable target from a fresh, known-good VM boot with read-only
commands such as `lsblk -o NAME,SIZE,TYPE,PTTYPE,FSTYPE,MOUNTPOINTS`
and `findmnt`. Do not retry the previous command, unmount arbitrary
devices, run `wipefs`, invoke Disko or assume the disk is blank.
Any deliberate reformat requires a separately reviewed fresh
disposable VM/disk and a fresh authorized install attempt.

## Actual disposable-disk fault testing

New Nix check: `forge-lab-failure-recovery`.

A lightweight NixOS QEMU guest boots from **/dev/vdb**. Its separate,
sparse **10 GiB /dev/vda** is entirely disposable. Its only injected
formatter is an immutable Nix-store script which:

1. Accepts exactly `--yes-wipe-all-disks` (otherwise fails).
2. Creates a real GPT on the guest's **/dev/vda only** using Parted.
3. Exits with a nonzero code immediately after writing the GPT.

The VM invokes the **actual** guarded `forge_executor_lab.py`
including root/QEMU safety, exact erase confirmation, fresh kernel
mount/boot ancestry and the one-shot transaction. It proves:

- the original attempt reaches `format-started`;
- the real GPT is visible on the disposable target;
- the transaction halts as `halted-after-format-started`;
- no LUKS mapper, account hash, installed system or successful
  installation phase appears;
- the root-owned 0600 marker remains after failure;
- a **second executable invocation** with the same confirmation is
  refused *before* starting another format;
- the read-only recovery report does not authorize writes or retry.

This test **does write a disposable VM disk**. It never accesses host
disks or physical hardware. It does not call the actual production
Disko layout; PR #43's separate full-install workflow still validates
the complete successful encrypted installation path.

## CI

Fast unit suite (no root and no disk operations):

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-lab-attempt-tests
```

Separate full-install CI now runs **two independent jobs in parallel**:

```sh
nix build --no-link -L .#checks.x86_64-linux.uefi-installed-boot
nix build --no-link -L .#checks.x86_64-linux.forge-lab-failure-recovery
```

This is a destructive-path change: **both jobs must pass on the PR
head before merging**, alongside existing fast, encrypted persistence,
desktop and real-root/nonroot adversarial security CI.

## Next after PR #44

Expand disposable-QEMU crash/interrupt and mount-replacement coverage,
design the separately privileged physical execution service with a
durable recovery policy, then connect the Forge GUI only after those
safety boundaries have been reviewed.

**Physical disk writing stays disabled.**
