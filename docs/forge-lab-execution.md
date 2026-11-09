# Forge Installer — guarded disposable VM installation (PR #31)

**Only the existing disposable QEMU lab executor can write a disk.**
This PR does not enable installation on physical hardware, connect GUI
writes, change any production credentials, or build a new ISO.

## What changed

PR #30 tested the encrypted mount attestation against real QEMU LUKS2,
Btrfs and EFI devices. PR #31 now places that **same read-only verification
between the two existing destructive lab steps**:

1. Verify disposable VM guard: root caller, exact QEMU/DMI identity,
   marker `/run/eduardos-disposable-install-lab`, test-only LUKS key,
   exact disposable target `/dev/vda` and explicit
   `ERASE DISPOSABLE /dev/vda` acknowledgement.
2. **Independently recheck the VM guard in the `install()` function,**
   preventing direct callers from bypassing the checks in `main()`.
3. Read kernel `lsblk`, mountinfo and swaps, then use the existing
   parent-ancestry protection logic. Fail if `/dev/vda` backs the running
   root, another mounted filesystem, swap, or an unverified live overlay.
4. Open **only** `/dev/vda` with `O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC`.
   Verify the held descriptor's major:minor against the graph and its
   live block path. Close the descriptor on success or failure.
5. Execute the **existing** lab-only Disko formatting script.
6. Verify the held block device still identifies `/dev/vda`. Invoke
   PR #30's `forge_mount_audit.audit('/dev/vda')`, which independently
   requires all five Btrfs subvolumes and EFI to be mounted from the
   expected disk, with no overlapping EFI and encrypted partition.
   Validate the audit's status, exact major:minor, six mountpoints and
   explicit read-only/credential-write-disabled fields.
7. **Only after the audit passes**, run the existing
   `nixos-install --root /mnt --system <lab-closure> --no-root-passwd`.
   If any check fails, `nixos-install` is not called.

This deliberately adds **no physical-disk execution path**.
The destructive command is still permanently pinned to the disposable
QEMU lab `/dev/vda`. A successful audit does not authorize erasure;
the lab's existing exact confirmation and VM-only safety controls remain
mandatory.

## Test coverage

The fast, unprivileged suite `test_forge_executor_lab.py` now checks:

- A direct `install()` call cannot bypass the disposable VM guard.
- A pre-format disk ancestry failure results in zero commands executed.
- A post-format mount audit failure prevents `nixos-install` (only the
  pre-existing Disko step may have run).
- An audit claiming the wrong disk, wrong mountpoints, or write-enabled
  status is rejected.
- The held disk is opened read-only and its FD is closed even if a
  consumer fails.
- The block device identity must remain the expected major:minor.

The existing **manual/nightly** full UEFI test
(`checks.x86_64-linux.uefi-installed-boot`) now also runs the
`forge-mount-audit` program against the actual formatted and mounted
disk, confirms the boot disk is refused, and confirms the target fails
its audit after `umount -R /mnt`.

### Commands

Fast tests in ordinary PR CI (no ISO, no disk operations):

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-installer-lab-tests
```

Full destructive test **only inside disposable QEMU** (manual/nightly):

```sh
nix build --no-link -L .#checks.x86_64-linux.uefi-installed-boot
```

The QEMU integration test is intentionally not launched on every PR
because it compiles and boots the complete installed system twice.
It remains available in the separate full-install GitHub workflow.

## Limitations / next milestones

- This PR continues to install the *lab* system profile with its
  disposable user, not yet PR #27's real-user installed profile.
- The lab path uses a fixture LUKS key file; it does not yet integrate
  PR #28's secure local account/LUKS credentials or PR #29's one-shot
  installed-user credential staging.
- Holding a **read-only** disk descriptor does not protect against all
  hotplug, remount or device-replacement races.
- Physical installation will require an entirely separate privileged
  worker with strict device-handle binding, independent authorization
  and encrypted-target checks at the point of use.
- The Forge Neon GUI remains read-only; there is no POST execution API.
- **No ISO build**, per the Alpha 0.2 strategic-build policy.

**Next milestone:** install the actual parameterized target profile and
provision its real-user credentials *inside the disposable VM*, then
verify LUKS unlock, greetd login and persistent account data.
