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
# The Compose mount is the CURRENT working tree, not GitHub's merged main.
# Explicitly identify detached checkpoint tags and source hash to stop
# repeated testing of an unchanged ISO after new PRs are merged.
revision="unknown (git executable or repository metadata unavailable)"
git_ref="unknown"
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  revision="$(git rev-parse HEAD)"
  git_ref="$(git symbolic-ref --quiet --short HEAD || git describe --tags --always HEAD)"
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "WARNING: dirty worktree; build includes uncommitted source changes" >&2
  fi
fi
echo "Source revision: $revision"
echo "Source checkout: $git_ref"
echo "Installer source sha256: $(sha256sum installer/forge_gui.py | cut -d' ' -f1)"
if [ "$git_ref" != main ] && [ "$git_ref" != unknown ]; then
  echo "NOTICE: Docker is building checkout '$git_ref', NOT current GitHub main" >&2
fi
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
cat > "$OUT/BUILDINFO.txt" <<EOF
eduardOS Alpha 0.2 ISO build identity
Source git revision: $revision
Source git ref: $git_ref
Forge GUI SHA256: $(sha256sum installer/forge_gui.py | cut -d' ' -f1)
Forge CSS SHA256: $(sha256sum installer/web/style.css | cut -d' ' -f1)
EOF
echo "Checksum: out/SHA256SUMS"
echo "Build identity: out/BUILDINFO.txt"
