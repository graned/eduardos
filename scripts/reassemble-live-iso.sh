#!/usr/bin/env bash
# Reassemble the downloaded GitHub artifact and validate the ISO checksum.
set -euo pipefail
if (( $# != 1 )); then
  echo "Usage: $0 <unpacked-artifact-directory>" >&2
  exit 2
fi
artifact_dir="$(cd "$1" && pwd)"
shopt -s nullglob
parts=( "$artifact_dir"/eduardos-alpha.iso.part-* )
if (( ${#parts[@]} == 0 )); then
  echo "No eduardos-alpha.iso.part-* files found" >&2
  exit 1
fi
if [[ ! -f "$artifact_dir/SHA256SUMS" ]]; then
  echo "Missing SHA256SUMS" >&2
  exit 1
fi
output="$artifact_dir/eduardos-alpha.iso"
if [[ -e "$output" ]]; then
  echo "Refusing to replace existing ISO: $output" >&2
  exit 1
fi
# Files have zero-padded numeric suffixes, so lexical order is part order.
cat "${parts[@]}" > "$output"
if ! ( cd "$artifact_dir" && sha256sum --check SHA256SUMS ); then
  rm -f "$output"
  echo "ISO checksum mismatch; refusing to retain reconstructed image" >&2
  exit 1
fi
echo "Verified ISO: $output"
