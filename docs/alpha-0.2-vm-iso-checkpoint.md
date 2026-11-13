# eduardOS Alpha 0.2 — VM-only installation release candidate

**Status:** Candidate awaiting ISO build and ISO-originated QEMU installation acceptance. Not yet a verified or released ISO.

## Scope

The live desktop continues opening the unprivileged, read-only Forge preview. A separate, deliberately launched command, `sudo forge-installer-vm`, enables the existing guarded installer **only inside disposable QEMU**. It requires root, an actual local TTY, QEMU DMI, the exact virtio target `/dev/vda` with alias `/dev/disk/by-id/virtio-root`, disk safety checks, and typed authorization. It cannot install to arbitrary physical disks.

**Irreversible operation:** this procedure erases the selected disposable VM drive. NEVER attach real devices, host partitions, USB passthrough drives, valuable qcow2 images, or physical-disk passthrough.

The current installed profile is intentionally a fixed VM test template, with hostname `edos-installed-lab` and username `testpilot`. Console-provided account and LUKS secrets are user-selected. This is not yet a general configurable physical installer.

## Build the candidate ISO

From the repository root run `nix build --out-link result -L .#live-iso`, or use GitHub Actions → **eduardOS Alpha live ISO** → **Run workflow** on the candidate branch. The workflow builds the ISO, checksums it, and checks diskless boot. Diskless boot success does NOT prove that installation from the ISO works.

## Acceptance runner — exact ISO, disposable disk, and two cold boots

On a **Linux x86_64 host with QEMU, OVMF firmware and qemu-img installed**, use
the helper below. It creates a fresh 16-GiB qcow2 and UEFI variable image in
a directory that must not already exist. It will **refuse an existing
destination**, and never accepts a physical disk device path as an argument.
The ISO is attached read-only. If your host's firmware paths are unusual,
set `EDOS_OVMF_CODE` and `EDOS_OVMF_VARS` to the relevant OVMF template
files. On Apple Silicon, use an equivalent x86_64 UEFI guest configured in
UTM; this helper is written for Linux QEMU.

```sh
# From the repo root, after building the current checkout (not an old tag):
bash scripts/accept-alpha02-iso-qemu.sh install \
  out/eduardos-alpha.iso out/alpha02-acceptance-001
```

Inside that **new VM**, confirm `readlink -f /dev/disk/by-id/virtio-root`
returns `/dev/vda`. Run `sudo forge-installer-vm` in an actual guest TTY,
type exactly `ERASE DISPOSABLE /dev/vda`, enter and confirm your LUKS and
account passwords, then open the printed loopback URL **inside that VM**.
Complete the Forge wizard with `edos-installed-lab` and `testpilot`,
select the fixed disposable VM disk, and wait for terminal state
`installed-lab-only`. **Do not retry** a partially formatted disk; destroy
the disposable acceptance directory and start over with a new one.

Shut down the guest normally after installation. Boot the *same* image with
the *same* OVMF variables, with the ISO now disconnected:

```sh
bash scripts/accept-alpha02-iso-qemu.sh boot - out/alpha02-acceptance-001
```

At UEFI startup, unlock LUKS with the password you chose and log in as
`testpilot`. Create a persistence witness in the installed user's home
directory, then shut down again:

```sh
printf 'alpha02-persisted\n' > ~/alpha02-acceptance-marker
sudo systemctl poweroff
```

Repeat a **full cold boot** (not rebooting the still-running VM) and verify
that the marker is still present:

```sh
bash scripts/accept-alpha02-iso-qemu.sh boot-again - out/alpha02-acceptance-001
# Inside the installed guest:
cat ~/alpha02-acceptance-marker
```

Record the ISO checksum in `out/alpha02-acceptance-001/ISO-SHA256`, the
`out/BUILDINFO.txt` source revision, and the observed installer phases,
LUKS unlock, PAM login and persistent marker. This is **operator-driven
release acceptance**, not a claim that the steps are already verified.
The existing NixOS QEMU CI covers encrypted installation, login and cold
boot from the lab test image, but the release additionally requires this
ISO-originated test.

## Disposable QEMU setup

Create a **new disposable qcow2** of at least 12 GiB. Allocate 4 GiB RAM and 2–4 CPUs. Present the target as virtio `/dev/vda` with serial `root`; the installer refuses other targets.

Example Linux/KVM command sequence:

```sh
qemu-img create -f qcow2 ./edos-disposable-vm.qcow2 16G
qemu-system-x86_64 -enable-kvm -m 4096 -smp 4 \
  -cdrom ./eduardos-alpha.iso -boot d \
  -drive if=none,id=vm-target,file=./edos-disposable-vm.qcow2,format=qcow2 \
  -device virtio-blk-pci,drive=vm-target,serial=root
```

After live boot, open a terminal and check `readlink -f /dev/disk/by-id/virtio-root` shows `/dev/vda`. Then run `sudo forge-installer-vm`.

Type **ERASE DISPOSABLE /dev/vda** at the root authorization prompt, followed by separate, confirmed LUKS and account credentials entered on the terminal. The launcher produces a private loopback Forge URL. Open it **inside the same VM**, select the disposable target, enter `edos-installed-lab` / `testpilot` in the wizard, then click **Install disposable VM**.

The browser never receives the secrets. The trusted operator's sealed, role-labelled Linux memfds are passed to the existing guarded executor. Cancellation after formatting requires manual recovery; never automatically retry an uncertain disk.

Once installed, shut down, detach the ISO, and boot the qcow2 with OVMF/UEFI. Unlock with the selected LUKS passphrase and log in as `testpilot`.

## Frozen Milestone 3 release gates

1. Build this exact ISO, check its SHA-256 and verify diskless boot.
2. Boot **the ISO itself** with a disposable target, install via Forge browser interaction, boot the resulting disk with OVMF, and prove encrypted login and second cold reboot.
3. Publish the verified artifact with known limitations and obtain explicit user approval.

This candidate is **not safe or authorized for physical-hardware installation**.

⚡ eduardOS — Forged in Darkness.
