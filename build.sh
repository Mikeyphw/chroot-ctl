#!/usr/bin/env bash
set -euo pipefail

MODULE_NAME="${MODULE_NAME:-chrootctl-magisk}"
OUT_DIR="${OUT_DIR:-./out}"
ZIP_NAME="${ZIP_NAME:-${MODULE_NAME}.zip}"
WHEELHOUSE_DIR="${WHEELHOUSE_DIR:-./wheelhouse}"

echo "[1/5] Cleaning old module output..."
rm -rf "$OUT_DIR" "$ZIP_NAME"

echo "[2/5] Rendering Magisk/KSU module..."
PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src" python3 - "$OUT_DIR" "$ZIP_NAME" "$WHEELHOUSE_DIR" <<'PY'
from pathlib import Path
import sys

from chrootctl.magisk import MagiskModuleConfig, render_magisk_module, validate_magisk_module, zip_magisk_module

out_dir = Path(sys.argv[1])
zip_path = Path(sys.argv[2])
wheelhouse_arg = Path(sys.argv[3])
wheelhouse_dir = wheelhouse_arg if wheelhouse_arg.exists() and any(wheelhouse_arg.glob("*.whl")) else None

render_magisk_module(
    out_dir,
    services=None,
    startup_targets=(),
    module_config=MagiskModuleConfig(offline_wheelhouse_dir=wheelhouse_dir),
)
validate_magisk_module(out_dir)
zip_magisk_module(out_dir, zip_path)
PY

echo "[3/5] Verifying required module files..."
required_paths=(
  "module.prop"
  "customize.sh"
  "post-fs-data.sh"
  "service.sh"
  "bin/chrootctl-magisk-helper"
  "bin/chrootctl-python-bootstrap"
  "system/bin/chrootctl"
)

for path in "${required_paths[@]}"; do
  if [[ ! -e "$OUT_DIR/$path" ]]; then
    echo "ERROR: missing module artifact: $path" >&2
    exit 1
  fi
done

echo "[4/5] Verifying zip root..."
python3 - "$ZIP_NAME" <<'PY'
import sys
import zipfile

zip_path = sys.argv[1]
required = {
    "module.prop",
    "customize.sh",
    "post-fs-data.sh",
    "service.sh",
    "bin/chrootctl-magisk-helper",
    "bin/chrootctl-python-bootstrap",
    "system/bin/chrootctl",
}
with zipfile.ZipFile(zip_path) as archive:
    names = set(archive.namelist())
missing = sorted(required - names)
if missing:
    raise SystemExit(f"zip is missing required root entries: {', '.join(missing)}")
if any(name.startswith("out/") for name in names):
    raise SystemExit("zip contains the output directory itself; expected module files at zip root")
PY

echo "[5/5] Done: $ZIP_NAME"
echo "Flash $ZIP_NAME in Magisk or KernelSU."
echo "Offline wheelhouse source: ${WHEELHOUSE_DIR} (used only when it contains .whl files)"
