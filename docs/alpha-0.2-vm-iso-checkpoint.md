# eduardOS Alpha 0.2 — VM-only installation release candidate

**Status:** Candidate awaiting ISO build and ISO-originated QEMU installation acceptance. Not yet a verified or released ISO.

## Scope

The live desktop continues opening the unprivileged, read-only Forge preview. A separate, deliberately launched command, `sudo forge-installer-vm`, enables the existing guarded installer **only inside disposable QEMU**. It requires root, an actual local TTY, QEMU DMI, the exact virtio target `/dev/vda` with alias `/dev/disk/by-id/virtio-root`, disk safety checks, and typed authorization. It cannot install to arbitrary physical disks.

**Irreversible operation:** this procedure erases the selected disposable VM drive. NEVER attach real devices, host partitions, USB passthrough drives, valuable qcow2 images, or physical-disk passthrough.

The current installed profile is intentionally a fixed VM test template, with hostname `edos-installed-lab` and username `testpilot`. Console-provided account and LUKS secrets are user-selected. This is not yet a general configurable physical installer.

## Build the candidate ISO

From the repository root run `nix build --out-link result -L .#live-iso`, or use GitHub Actions → **eduardOS Alpha live ISO** → **Run workflow** on the candidate branch. The workflow builds the ISO, checksums it, and checks diskless boot. Diskless boot success does NOT prove that installation from the ISO works.

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
