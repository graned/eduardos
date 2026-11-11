{ pkgs }:
# Forge installer artwork is independent from desktop and boot backgrounds.
# Decode the approved lossless image and write its native-resolution PNG
# during the Nix build. No remote download and no runtime conversion.
let
  python = pkgs.python3.withPackages (ps: [ ps.pillow ]);
  parts = ../../themes/forge-eclipse/installer-source;
in
pkgs.runCommand "eduardos-forge-eclipse-installer-png" {
  nativeBuildInputs = [ pkgs.coreutils python ];
} ''
  mkdir -p "$out"
  cat ${parts}/part-*.b64 | base64 --decode > "$TMPDIR/approved-installer.webp"
  echo "91b2c9f7a02dc83f0033b9bdc63223f24d2074480cbd13ca2b38bad1cc469ff9  $TMPDIR/approved-installer.webp" | sha256sum --check --status
  python - <<'PY'
import os
from PIL import Image
source = os.path.join(os.environ["TMPDIR"], "approved-installer.webp")
dest = os.path.join(os.environ["out"], "installer.png")
with Image.open(source) as art:
    if art.size != (1672, 941):
        raise SystemExit("Unexpected Forge installer artwork dimensions")
    art.convert("RGB").save(dest, format="PNG", optimize=True)
PY
  test -s "$out/installer.png"
  test "$(head -c 4 "$out/installer.png" | od -An -tx1 | tr -d '[:space:]')" = 89504e47
''