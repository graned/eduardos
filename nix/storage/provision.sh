#!/usr/bin/env bash
# eduardOS storage prototype: destructive only with an explicit confirmation.
# Use on disposable, unmounted disks. Not yet the production installer.
set -euo pipefail

usage() {
  echo "Usage: edos-storage-provision --destroy-disposable-disk /dev/DEVICE" >&2
  echo "Requires EDOS_LUKS_KEYFILE to point to a pre-existing key file." >&2
  exit 2
}

[[ ${1:-} == "--destroy-disposable-disk" && $# -eq 2 ]] || usage
disk=$2
[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
[[ -b "$disk" && "$(lsblk -dnro TYPE "$disk")" == "disk" ]] ||
  { echo "Expected a whole block disk: $disk" >&2; exit 1; }
[[ -n ${EDOS_LUKS_KEYFILE:-} && -f "$EDOS_LUKS_KEYFILE" ]] ||
  { echo "EDOS_LUKS_KEYFILE is required" >&2; exit 1; }
[[ -s "$EDOS_LUKS_KEYFILE" ]] ||
  { echo "Key file must not be empty" >&2; exit 1; }

# Stop rather than ever destroy a mounted/active disk.
if lsblk -nrpo MOUNTPOINTS "$disk" | grep -q '[^[:space:]]'; then
  echo "Refusing to erase a mounted disk: $disk" >&2
  exit 1
fi
if lsblk -nrpo TYPE "$disk" | grep -Eq 'crypt|lvm|raid'; then
  echo "Refusing to erase a disk with active mappings: $disk" >&2
  exit 1
fi
[[ ! -e /dev/mapper/edos-crypt ]] ||
  { echo "Mapper edos-crypt is already active" >&2; exit 1; }

echo "WARNING: erasing all partitions and data on $disk" >&2
parted --script "$disk" mklabel gpt
parted --script "$disk" mkpart ESP fat32 1MiB 1025MiB
parted --script "$disk" set 1 esp on
parted --script "$disk" mkpart edos-crypt 1025MiB 100%
partprobe "$disk"
udevadm settle

case "$disk" in
  *[0-9]) esp="${disk}p1"; cryptpart="${disk}p2" ;;
  *) esp="${disk}1"; cryptpart="${disk}2" ;;
esac
[[ -b "$esp" && -b "$cryptpart" ]] ||
  { echo "Partition nodes did not appear" >&2; exit 1; }

mkfs.vfat -F 32 -n EDOS-EFI "$esp"
cryptsetup luksFormat --type luks2 --batch-mode --key-file "$EDOS_LUKS_KEYFILE" "$cryptpart"
cryptsetup open --type luks --key-file "$EDOS_LUKS_KEYFILE" "$cryptpart" edos-crypt

top=$(mktemp -d /run/edos-storage.XXXXXX)
cleanup() {
  mountpoint -q "$top" && umount "$top"
  cryptsetup close edos-crypt || true
  rmdir "$top" || true
}
trap cleanup EXIT
mkfs.btrfs -f -L edos-system /dev/mapper/edos-crypt
mount /dev/mapper/edos-crypt "$top"
for name in root home nix persist snapshots; do
  btrfs subvolume create "$top/@$name"
done
sync
echo "Created EDOS-EFI and encrypted Btrfs subvolumes @root, @home, @nix, @persist, @snapshots" >&2
