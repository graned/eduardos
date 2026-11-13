#!/usr/bin/env bash
# Alpha 0.2 acceptance: boot the ACTUAL ISO, install ONLY to a newly created
# disposable qcow2, then cold-boot that same image with persistent UEFI vars.
# This script NEVER supplies a host block device or automates disk erasure.
set -euo pipefail
usage() {
  echo "Usage: $0 install|boot|boot-again <ISO-file-for-install> <NEW-acceptance-directory>" >&2
  echo "For boot / boot-again, pass '-' as the ISO filename." >&2
  echo "Optional: EDOS_OVMF_CODE and EDOS_OVMF_VARS (firmware template paths)." >&2
  exit 2
}
(( $# == 3 )) || usage
phase="$1"; iso="$2"; root="$3"
case "$phase" in install|boot|boot-again) ;; *) usage ;; esac
for bin in qemu-img qemu-system-x86_64 sha256sum realpath; do
  command -v "$bin" >/dev/null || { echo "Missing $bin" >&2; exit 2; }
done
# Reuse no existing disk on installation. Avoid accidentally reformatting
# arbitrary guest images by accepting only directories created by this flow.
if [[ "$phase" == install ]]; then
  [[ -f "$iso" && ! -L "$iso" ]] || { echo "Expected a regular ISO file" >&2; exit 2; }
  [[ ! -e "$root" && ! -L "$root" ]] || {
    echo "Installation needs a NEW, nonexistent acceptance directory" >&2; exit 2;
  }
  iso="$(realpath "$iso")"
  [[ "$iso" == *.iso ]] || { echo "Expected an .iso file" >&2; exit 2; }
else
  [[ "$iso" == "-" ]] || { echo "Boot phases cannot take an ISO" >&2; exit 2; }
  [[ -d "$root" && ! -L "$root" ]] || { echo "Missing acceptance directory" >&2; exit 2; }
fi
# A fresh local directory holds our ONLY target; no raw disk, partition,
# USB, drive passthrough, network disk or external block node is attached.
if [[ "$phase" == install ]]; then
  umask 077
  mkdir -m 700 -- "$root"
fi
root="$(realpath "$root")"
disk="$root/disposable-vda.qcow2"
vars="$root/OVMF_VARS.fd"
manifest="$root/ISO-SHA256"
code="${EDOS_OVMF_CODE:-}"
template="${EDOS_OVMF_VARS:-}"
for candidate in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd; do
  [[ -n "$code" ]] || { [[ ! -f "$candidate" ]] || code="$candidate"; }
done
for candidate in /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd /usr/share/edk2/ovmf/OVMF_VARS.fd /usr/share/edk2/x64/OVMF_VARS.4m.fd; do
  [[ -n "$template" ]] || { [[ ! -f "$candidate" ]] || template="$candidate"; }
done
[[ -f "$code" && -f "$template" ]] || {
  echo "OVMF UEFI CODE and VARS template required (EDOS_OVMF_CODE/EDOS_OVMF_VARS)" >&2
  exit 2
}
if [[ "$phase" == install ]]; then
  [[ ! -e "$disk" && ! -L "$disk" && ! -e "$vars" && ! -L "$vars" ]] || {
    echo "Refusing to overwrite an existing guest disk or UEFI state" >&2; exit 2;
  }
  qemu-img create -f qcow2 -o backing_file=off "$disk" 16G 2>/dev/null || qemu-img create -f qcow2 "$disk" 16G
  cp -- "$template" "$vars"
  sha256sum "$iso" | cut -d' ' -f1 > "$manifest"
  printf 'ISO SHA256: %s\n' "$(cat "$manifest")"
else
  [[ -f "$disk" && ! -L "$disk" && -f "$vars" && ! -L "$vars" && -s "$manifest" ]] || {
    echo "Missing or unsafe disposable guest image/UEFI state/ISO manifest" >&2; exit 2;
  }
  # Do not accept an externally supplied qcow2 with a backing file.
  qemu-img info --output=json "$disk" | grep -Eq '"format"[[:space:]]*:[[:space:]]*"qcow2"' || exit 2
  if qemu-img info --output=json "$disk" | grep -Eq '"backing-filename"[[:space:]]*:'; then
    echo "Refusing guest disk that has a backing file" >&2; exit 2
  fi
fi
args=(
  -machine q35,accel=kvm:tcg
  -m 4096 -smp 4
  -device virtio-vga
  -drive "if=pflash,format=raw,readonly=on,file=$code"
  -drive "if=pflash,format=raw,file=$vars"
  -drive "if=none,id=edos-target,file=$disk,format=qcow2"
  -device virtio-blk-pci,drive=edos-target,serial=root
  -nic user,model=virtio-net-pci
  -serial mon:stdio
)
if [[ "$phase" == install ]]; then
  args+=(-drive "if=none,id=edos-cd,file=$iso,media=cdrom,readonly=on" -device ide-cd,drive=edos-cd -boot order=d)
  echo "ISO: $iso"
  echo "Disposable target: $disk (16 GiB, virtio serial 'root')"
  echo "IN THE GUEST, verify /dev/disk/by-id/virtio-root -> /dev/vda."
  echo "Then run sudo forge-installer-vm, enter consent and credentials at a TTY,"
  echo "open its 127.0.0.1 URL inside this VM and complete Forge wizard."
  echo "Shut down the VM normally AFTER Forge reports installed-lab-only."
else
  echo "Booting INSTALLED DISPOSABLE DISK WITHOUT THE ISO ($phase)."
  echo "Unlock LUKS and log in as testpilot. Verify files remain after second cold boot."
fi
echo "Only the disposable qcow2 is attached as a writable block target."
exec qemu-system-x86_64 "${args[@]}"
