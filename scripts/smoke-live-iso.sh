#!/usr/bin/env bash
# Boots a preview ISO in disposable, diskless QEMU; no physical disks attached.
set -euo pipefail
if (( $# != 1 )) || [[ ! -f "$1" ]]; then
  echo "Usage: $0 <eduardos-alpha.iso>" >&2
  exit 2
fi
iso="$(realpath "$1")"
command -v qemu-system-x86_64 >/dev/null || {
  echo "qemu-system-x86_64 is required" >&2
  exit 2
}
timeout_seconds="${EDOS_BOOT_TIMEOUT_SECONDS:-300}"
if ! [[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "EDOS_BOOT_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi
tmpdir="$(mktemp -d)"
serial_log="$tmpdir/serial.log"
qemu_pid=""
cleanup() {
  if [[ -n "$qemu_pid" ]] && kill -0 "$qemu_pid" 2>/dev/null; then
    kill "$qemu_pid" 2>/dev/null || true
    wait "$qemu_pid" 2>/dev/null || true
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT INT TERM
touch "$serial_log"
# Deliberately attach NO virtual hard drives, USB passthrough, host folders
# or network devices. The only storage is the read-only ISO as a CD-ROM.
qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg -m 4096 -smp 2 \
  -cdrom "$iso" -boot d -vga std \
  -display none -serial "file:$serial_log" -monitor none \
  -nic none -no-reboot >"$tmpdir/qemu.log" 2>&1 &
qemu_pid=$!
marker="EDOS_LIVE_BOOT_OK=alpha-0.2-vm-rc"
started="$(date +%s)"
while :; do
  if grep -Fq "$marker" "$serial_log"; then
    echo "PASS: eduardOS live ISO reached multi-user.target in diskless QEMU"
    exit 0
  fi
  if ! kill -0 "$qemu_pid" 2>/dev/null; then
    echo "QEMU exited before boot acknowledgement" >&2
    tail -n 40 "$serial_log" >&2 || true
    cat "$tmpdir/qemu.log" >&2 || true
    exit 1
  fi
  if (( $(date +%s) - started >= timeout_seconds )); then
    echo "Timed out waiting for live ISO serial boot acknowledgement" >&2
    tail -n 80 "$serial_log" >&2 || true
    cat "$tmpdir/qemu.log" >&2 || true
    exit 1
  fi
  sleep 2
done
