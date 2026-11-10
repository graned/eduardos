#!/bin/sh
set -eu

KEY=/run/secrets/nixbuild_key
OUT=/out
FEATURES=benchmark,big-parallel,ca-derivations,kvm,nixos-test

if [ ! -f "$KEY" ] || [ ! -s "$KEY" ]; then
  echo "Missing private key. Export NIXBUILD_SSH_KEY as an absolute path to the key registered with nixbuild.net." >&2
  exit 2
fi
if [ ! -f flake.nix ]; then
  echo "Run this from the eduardOS repository root with: docker compose -f builder/compose.yml run --build --rm iso" >&2
  exit 2
fi

mkdir -p "$OUT"
echo "eduardOS: x86_64 ISO build via nixbuild.net"
echo "Build environment: container; host system Nix/SSH configuration is untouched."
# SSH authentication and host-key verification happen as part of the Nix
# remote builder connection. nixbuild.net does not provide a general shell.

# Disable local derivation execution entirely; this container is the Nix
# evaluator and result receiver, not an x86_64 builder.
builder="ssh://eu.nixbuild.net x86_64-linux $KEY 32 1 $FEATURES"
path="$(
  nix build \
    --no-link \
    --print-out-paths \
    --print-build-logs \
    --builders "$builder" \
    --max-jobs 0 \
    --option builders-use-substitutes true \
    '.#live-iso'
)"
if [ ! -d "$path/iso" ]; then
  echo "Expected ISO output directory was not produced: $path/iso" >&2
  exit 4
fi
iso="$(find "$path/iso" -maxdepth 1 -type f -name '*.iso' -print -quit)"
if [ -z "$iso" ]; then
  echo "The Nix build returned successfully but no ISO was found." >&2
  exit 4
fi

# A temporary file prevents a partially copied ISO from masquerading as
# the final image if Docker exits or the host disk fills.
tmp="$OUT/.eduardos-alpha.iso.partial"
trap 'rm -f "$tmp"' EXIT
cp "$iso" "$tmp"
mv -f "$tmp" "$OUT/eduardos-alpha.iso"
(
  cd "$OUT"
  sha256sum eduardos-alpha.iso > SHA256SUMS
)
echo "ISO ready: out/eduardos-alpha.iso"
echo "Checksum: out/SHA256SUMS"
