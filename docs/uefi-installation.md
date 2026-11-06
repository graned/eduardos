# UEFI / Disko installation profile — PR #16

This milestone turns PR #15's tested **data-disk layout** into a
declarative NixOS configuration with UEFI boot, encrypted root, and
Btrfs mounts. It is **not yet a proven installed-and-booted disk image**.

## Lab-only NixOS profile

`nixosConfigurations.eduardos-uefi-lab` imports the same eduardOS
desktop modules as the tested VM, plus:

- `disko.nixosModules.disko`
- `nix/storage/disko-layout.nix`
- `hosts/uefi-lab/default.nix`

The lab profile hardcodes `/dev/vda` and explicitly permits unstable
disk naming **for disposable QEMU only**. It MUST NOT be used to
partition physical hardware.

## Proposed install layout

| Device | Filesystem | Mount |
|---|---|---|
| GPT partition 1, 1 GiB | FAT32 EFI System Partition | `/boot` |
| GPT partition 2, remaining space | LUKS2 `edos-crypt` + Btrfs | see below |

Within the single encrypted Btrfs volume:

| Subvolume | Mountpoint |
|---|---|
| `/@root` | `/` |
| `/@home` | `/home` |
| `/@nix` | `/nix` |
| `/@persist` | `/persist` |
| `/@snapshots` | `/.snapshots` |

Each uses `compress=zstd,noatime`; the ESP uses `umask=0077`.
Systemd-boot is enabled and NixOS 26.05's systemd-based initrd handles
the encrypted root; Disko owns the mount definitions.

**No LUKS password or key is committed.** Disko's configuration leaves
interactive passphrase input enabled, with discards disabled by default.
Store recovery material outside the installed device.

## Safety for eventual physical installation

The storage module has no default disk. The installer must force the
user to select one and display its stable `/dev/disk/by-id/` identity
before destructive provisioning. Device names like `/dev/vda` are
allowed only with `eduardos.storage.allowUnstableDeviceName = true`,
reserved for disposable test guests.

This PR does **not** implement a safe interactive disk picker, backups,
dual boot, graphical installer, real-disk migration, physical-hardware
validation, or unattended encryption unlock. Do not execute Disko's
destructive commands on an existing installation.

## Validation

```sh
nix flake check --no-build
nix build .#checks.x86_64-linux.uefi-storage-layout -L
nix build .#checks.x86_64-linux.uefi-install-config -L
```

The layout check verifies GPT, LUKS, Btrfs and all six mounts
(`/boot` plus five encrypted subvolumes). The system closure check
builds the NixOS UEFI profile, including its boot setup and initrd.
Existing boot, encrypted-data persistence and graphical theme checks
remain mandatory. The expensive full Disko installation test runs as a
separate nightly or manual GitHub Actions workflow instead of blocking
every ordinary pull request.

**Next milestone:** provision a temporary disk with Disko itself,
install eduardOS onto it with `nixos-install`, boot that installed
image under QEMU with OVMF, unlock its LUKS partition, verify
`/home` and `/persist` across a real reboot, then test recovery.
Until then, the UEFI closure check is not proof of bootability.

## PR #17 — installed encrypted UEFI boot integration test

The new `uefi-installed-boot` check runs a separate **installer** VM and
then a **firmware-booted** target VM using the same disposable qcow2 image:

1. Boot a disposable installation environment with an empty target disk.
2. Use the Disko-generated destroy/format/mount script for GPT, EFI,
   LUKS2, and the five Btrfs subvolumes.
3. Generate the throwaway encryption passphrase inside the installer
   VM at `/run/edos-test-passphrase`. This plaintext exists solely in
   the ephemeral CI guest, never in an installed initrd or real host.
4. Install the actual eduardOS NixOS system closure using `nixos-install`,
   without using the temporary rootfs or kernel-direct QEMU boot path.
5. Stop the installer VM and start the same disk in a UEFI/OVMF guest,
   respond to the *interactive* LUKS unlock prompt, and assert both
   filesystem mounts and installed application binaries.
6. Power down and boot again; verify persistent `/home` and
   `/persist` markers remain intact.

```sh
nix build .#checks.x86_64-linux.uefi-installed-boot -L
```

**Do not treat this as production hardware certification.** Test failures
must not be bypassed with kernel-direct boot, a baked-in unlock key, or
mounting the host's Nix store in place of the installed system. CI uses
test instrumentation and a disposable password solely to automate
repeated installation verification. Real disk discovery, backups and
recovery UX are separate installer milestones.

## How to run the full installation test

The normal PR workflow (`.github/workflows/nixos-vm.yml`) covers fast
evaluation, encrypted persistence, VM boot, and graphical themes. The
full encrypted install is isolated in `.github/workflows/full-install.yml`
and runs nightly on the default branch or manually from GitHub Actions
once the workflow file is merged to the default branch.

### GitHub Actions (easiest)

1. Once merged, open **Actions → eduardOS full encrypted installation**.
2. Select **Run workflow** and choose the branch you want to test.
3. Open the **Full Disko install, OVMF unlock and reboot** job.
4. A successful run must finish both the first boot/unlock and the second
   cold boot/persistence checks. A green PR smoke test alone does not prove
   that a fresh disk installation works.

### Run locally in a disposable VM or Linux host (advanced)

The existing test is **automated, not a bootable installation ISO**. Use
an x86_64 Linux environment with Nix flakes and QEMU/KVM support. If
running inside a VM, enable nested virtualization and confirm `/dev/kvm`
exists. Allocate at least 4 vCPUs, 8 GiB RAM and ~40 GiB of free disk
space for the test and Nix store; additional capacity may be necessary
for an uncached build. This will create and destroy only test-owned
virtual disk images, **not a disk passed through from your host**.

```sh
git clone https://github.com/graned/eduardos.git
cd eduardos
git switch feat/uefi-installed-boot-test
nix --extra-experimental-features 'nix-command flakes' \
  flake check --no-build
nix --extra-experimental-features 'nix-command flakes' \
  build -L .#checks.x86_64-linux.uefi-installed-boot
```

Do not redirect the test to a physical disk. The lab profile hardcodes
`/dev/vda`; it is exclusively for disposable QEMU images. Never run
its Disko `destroyFormatMount` script against a real device.

### Manual VM UX testing — what is and is not ready

The current `nixosConfigurations.eduardos-uefi-lab` is a **lab-only
NixOS profile**, not a safe general installer. You can meaningfully
validate the test's install, encrypted unlock, UEFI boot and persistence
behavior today through the automated nested-QEMU test. Do not assume
there is a supported graphical ISO, device picker, recovery flow or
safe installation procedure for an arbitrary VirtualBox/VMware disk.
Those are separate milestones. Manual interactive installation should
wait for a dedicated disposable-VM installer guide and an installable
image rather than guessing destructive commands.
