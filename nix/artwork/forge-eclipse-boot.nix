{ pkgs }:
# Boot-only background: the approved image is preserved losslessly in Git.
# Decode and resize to real PNGs once at Nix build time, never at boot.
let
  python = pkgs.python3.withPackages (ps: [ ps.pillow ]);
  parts = ../../themes/forge-eclipse/boot-source;
in
pkgs.runCommand "eduardos-forge-eclipse-boot-pngs" {
  nativeBuildInputs = [ pkgs.coreutils python ];
} ''
  mkdir -p "$out"
  cat ${parts}/part-*.b64 | base64 --decode > "$TMPDIR/boot-source.webp"
  echo "c65bed422ee974a33bfd5d2b7908c91aa1307634bc34cad61b5b060886810811  $TMPDIR/boot-source.webp" | sha256sum --check --status
  python - <<'PY'
import os
from PIL import Image, ImageOps
source = os.path.join(os.environ["TMPDIR"], "boot-source.webp")
destination = os.environ["out"]
with Image.open(source) as original:
    if original.size != (1672, 941):
        raise SystemExit("Unexpected Forge Eclipse boot artwork dimensions")
    for name, size in (
        ("bios.png", (800, 600)),
        ("efi.png", (1280, 720)),
        ("grub.png", (1280, 720)),
    ):
        # Cover the available screen without distorting figures or logo.
        image = ImageOps.fit(original.convert("RGB"), size,
                             method=Image.Resampling.LANCZOS,
                             centering=(0.5, 0.5))
        image.save(os.path.join(destination, name), format="PNG",
                   optimize=True)
PY
  for file in "$out"/bios.png "$out"/efi.png "$out"/grub.png; do
    test -s "$file"
    test "$(head -c 4 "$file" | od -An -tx1 | tr -d '[:space:]')" = 89504e47
  done
'';
