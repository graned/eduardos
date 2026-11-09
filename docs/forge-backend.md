# Forge Installer — Trusted Backend Boundary (PR #29)

**Not yet a usable or production-safe installer.** This PR introduces a
root-only backend library with a read-only block-device handle, encrypted
mountpoint attestation and a limited account-hash staging operation. It
does not partition, format, mount, install NixOS or expose any GUI write
API. No ISO build is included.

## Why this is a separate milestone

PRs #23–#26 introduced the disk identity review, exact consent, active
system ancestry checks and live ISO storage provenance. PR #28 added
private account hash staging and a sealed in-memory LUKS descriptor.

Those pieces still need to be connected behind a trust boundary that
**cannot confuse a source disk, target disk or mounted filesystem**.
PR #29 provides the first composed, root-only backend interface in
`installer/forge_backend.py` and independent tests.

## Phase 1: Prepare and hold selected disk (read-only)

The trusted caller must supply an eligible fresh disk review, exact
`ERASE /dev/disk/by-id/<selected-id>` consent and a valid username and
hostname. `prepare_target(...)` then:

1. Requires root and independently calls the existing
   `forge_privileged_guard.privileged_preflight` (disk identity,
   current root/boot ancestry, swap, and live media protection).
2. Resolves the stable by-id alias and opens its block device
   **O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC**.
3. Verifies `fstat` identifies the exact reviewed kernel major:minor
   block device, then verifies the original by-id alias still points to
   the same device.
4. Keeps the read-only descriptor open within a scoped
   `with prepare_target(...) as session:` context; closes it even on
   failure. It does not expose any disk write operation.

This is **not** a disk lock, disk-erasure authorization, or proof against
hotplug/driver replacement. A future destructive backend will need
independent last-moment device checks and an explicitly reviewed
disposable-VM execution protocol.

## Phase 2: Attest already-mounted encrypted destination

After a separately reviewed installer has formatted and mounted the
target, `attest_target_mounts(selected_devno, lsblk_data, mountinfo)`
verifies these exact mountpoints:

| Mountpoint | Filesystem | Mount root |
|---|---|---|
| /mnt | Btrfs | /@root |
| /mnt/home | Btrfs | /@home |
| /mnt/nix | Btrfs | /@nix |
| /mnt/persist | Btrfs | /@persist |
| /mnt/.snapshots | Btrfs | /@snapshots |
| /mnt/boot | FAT32 (vfat) | / |

It refuses missing/duplicate/unexpected target mounts, incorrect
subvolume roots, unencrypted Btrfs sources, a missing `edos-crypt`
mapper, a mapper physically backed by another disk, or EFI mounted from
any disk other than the held target. Major:minor block ancestry follows
all known parents; it does not assume one-parent storage.

The shared kernel mountinfo parser now exposes the *mount root field*
needed to distinguish Btrfs subvolumes independently of their mount
device number. The backend does not create any mountpoints.

## Phase 3: Stage only the account hash

`HeldTarget.stage_account_hash(password)` may be invoked only once
while the prepared session is unexpired (120 seconds). It independently
rechecks the held read-only block descriptor, stable by-id alias,
physical hardware properties, and current boot ID after partitioning.

Before calling PR #28's hash writer, it additionally verifies:

- All expected mounts and encrypted target provenance.
- The root directory descriptor is owned by root.
- The current root and persist directory device numbers agree with
  the kernel mount table.
- The stable by-id alias has not changed during hashing.

It then writes only the salted account hash at
`/persist/eduardos/credentials/<username>.hash` on the already mounted
target through a checked root directory descriptor. The result contains
no secret material. There is no disk formatter or full-system installer
in this library, and no runnable command enabling writes.

**Limitations:** The 120-second session does not yet accommodate full
multi-minute installs, mount race containment (e.g. mount namespaces),
credential process memory hardening, or device-replacement prevention.
We deliberately keep a single-use ephemeral session and do **not** wire
it into production. Later PRs need disposable-VM integration and
security review before any physical hardware workflow.

## Tests — no ISO

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-backend-tests
```

CI exercises synthetic GPT/LUKS/Btrfs block graphs and mountinfo records,
including EFI on another drive, mapper on another disk, missing/extra
mounts, wrong subvolumes, unencrypted roots, malformed consent,
preflight refusal, wrong target device, expired/reused sessions,
read-only descriptor opening/closing and credential staging ordering.

No root privileges or real disks are used in the test suite. The
existing full installer fixture check also picks up the new tests.
The live ISO and separate destructive QEMU lab executor are unchanged.

## Next steps toward Alpha 0.2

1. Test a realistic *mounted* LUKS2/Btrfs disk in a disposable QEMU
   integration environment and confirm real mountinfo conventions.
2. Move the destructive Disko/nixos-install path behind a separately
   audited, isolated executor; never infer authorization from a hash
   or from a successful read-only preflight.
3. Securely collect account and LUKS credentials through a trusted
   local interface, then connect the backend to the graphical wizard.
4. Verify first login and two cold boots on disposable disks.
5. Only then produce the strategic Alpha 0.2 installable ISO.

**Do not run this as an installer against real hardware.**
