{ pkgs }:
# Forge Eclipse wallpaper/installer art: source pixels are encoded as a
# lossless WebP to fit GitHub connector upload limits, then converted to
# a genuine full-resolution PNG once during the Nix build.
# The source is split into fixed, ordered base64 fragments; no network access.
let
  python = pkgs.python3.withPackages (ps: [ ps.pillow ]);
  parts = ../../themes/forge-eclipse/artwork-source;
in
pkgs.runCommand "eduardos-forge-eclipse-approved-png" {
  nativeBuildInputs = [ pkgs.coreutils python ];
} ''
  mkdir -p "$out"
  cat ${parts}/part-*.b64 | base64 --decode > "$TMPDIR/approved.webp"
  echo "d68b0d18d2a804c2799b528b47737b66ad10c74c5afc4663d198923a35d7be7e  $TMPDIR/approved.webp" | sha256sum --check --status
  python - <<'PY'
import os
from PIL import Image
source = os.path.join(os.environ["TMPDIR"], "approved.webp")
dest = os.path.join(os.environ["out"], "wallpaper.png")
with Image.open(source) as art:
    if art.size != (1672, 941):
        raise SystemExit("Unexpected Forge Eclipse artwork dimensions")
    art.convert("RGBA").save(dest, format="PNG", optimize=True)
PY
  test -s "$out/wallpaper.png"
  test "$(head -c 4 "$out/wallpaper.png" | od -An -tx1 | tr -d '[:space:]')" = 89504e47
''