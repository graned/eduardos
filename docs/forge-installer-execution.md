# Forge Installer — guarded disposable-VM execution (PR #22)

**VM lab only. This is not a production installer, not a recovery utility,
and must never be run on a physical machine.**

PR #22 introduces the first actual execution stage for the installation
pipeline, but wires it **only** into our existing QEMU installation lab.
The graphical Forge Neon wizard remains strictly read-only, and the
release ISO remains unchanged. No new ISO is built in this PR.

## Why a separate lab executor?

The repository already had a complete `uefi-installed-boot` test
covering Disko GPT/EFI/LUKS2/Btrfs, `nixos-install`, OVMF unlock,
and two cold boots. Instead of implementing a second disk formatter,
the lab executor calls the *same Nix-evaluated Disko
`destroyFormatMount` script* and the same installed system closure.

The executor requires **all** of the following, failing closed:
- Explicit `--execute` and an exact confirmation phrase:
  `ERASE DISPOSABLE /dev/vda`
- Root privileges inside the disposable QEMU/KVM guest.
- A guest-only `/run/eduardos-disposable-install-lab` marker with
  exactly `EDOS-LAB-ONLY`.
- DMI hardware identification consistent with QEMU/KVM.
- The hard-coded **test-only** disk `/dev/vda` (no dynamic device
  argument), at least 8 GiB, a whole writable non-removable disk.
- No mounts, swap or active encrypted/LVM/RAID child mappings on the
  selected target. A check rejects a root filesystem source that
  appears to originate on `/dev/vda`.
- A pre-created regular `/run/edos-test-passphrase` file with mode
  0600 and a nontrivial passphrase, located only in the disposable VM.
- Executable Disko script and NixOS system closure paths residing under
  `/nix/store/`.

No shell interpolation of disk paths is used; subprocesses receive
argument arrays and stop on nonzero exits. The test key is never
committed to the repo and is never embedded into the installed
NixOS closure.

**Limitations:** These are safety gates for a controlled test
environment, **not** safeguards adequate for physical hardware.
There is not yet a production target-identity revalidation protocol,
user credential setup, full-disk backup check, multi-disk protection,
rollback or privileged GUI bridge.

## Validation (without building an ISO)

Fast, unprivileged tests:

```sh
nix build --no-link .#checks.x86_64-linux.forge-installer-lab-tests
```

The fixture tests assert that execution is blocked by default,
requires the exact confirmation phrase, refuses failed guards,
uses argument-vector execution, and only reaches the test writer
after explicit approval and successful guards.

The full executable integration test remains isolated from normal
pull-request CI:

```sh
nix build --no-link -L .#checks.x86_64-linux.uefi-installed-boot
```

Run this **only** from an x86_64 Linux QEMU/KVM host or through the
manual/nightly `.github/workflows/full-install.yml`. It provisions a
temporary qcow2 disk, installs the actual eduardOS closure, boots it with
OVMF, unlocks LUKS, and verifies persisted data after reboot. It cannot
be run meaningfully on bare metal.

The test makes a disposable LUKS passphrase and the one-time lab
marker in the *installer guest* before invoking the guard, then
preserves the previous OVMF boot assertions. It must not attach or
pass through any physical disk.

## Next milestone

A production-grade installer requires separate hardening:
hardware/disk identity snapshots and revalidation, isolation from
the GUI process, secure password handling, a physical hardware
compatibility policy, and thorough destructive-operation tests
against disposable images. Only once those parts pass do we build
Alpha 0.2's ISO and test it in UTM.
