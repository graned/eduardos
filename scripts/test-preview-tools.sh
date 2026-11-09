#!/usr/bin/env bash
# Fast non-Nix tests: no QEMU, ISO or disk access.
set -euo pipefail
bash -n scripts/reassemble-live-iso.sh scripts/smoke-live-iso.sh
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
mkdir "$temp/good" "$temp/bad"
printf 'eduardOS-preview-fixture\n' > "$temp/original"
hash="$(sha256sum "$temp/original" | cut -d ' ' -f 1)"
printf '%s  eduardos-alpha.iso\n' "$hash" > "$temp/good/SHA256SUMS"
split -b 7 --numeric-suffixes=0 --suffix-length=3 \
  "$temp/original" "$temp/good/eduardos-alpha.iso.part-"
bash scripts/reassemble-live-iso.sh "$temp/good"
cmp "$temp/good/eduardos-alpha.iso" "$temp/original"
if bash scripts/reassemble-live-iso.sh "$temp/good"; then
  echo "Reassembly must refuse overwrite" >&2
  exit 1
fi
cp "$temp/good/SHA256SUMS" "$temp/bad/SHA256SUMS"
cp "$temp/good"/eduardos-alpha.iso.part-* "$temp/bad/"
printf 'tampered' >> "$temp/bad/eduardos-alpha.iso.part-000"
if bash scripts/reassemble-live-iso.sh "$temp/bad"; then
  echo "Tampered artifact must be rejected" >&2
  exit 1
fi
test ! -f "$temp/bad/eduardos-alpha.iso"
echo "PASS: ISO reassembly, checksum failure and overwrite refusal"
