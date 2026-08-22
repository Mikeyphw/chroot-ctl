#!/usr/bin/env bash
set -euo pipefail

MODULE_NAME="${MODULE_NAME:-chrootctl-magisk}"
OUT_DIR="${OUT_DIR:-./out}"
ZIP_NAME="${ZIP_NAME:-${MODULE_NAME}.zip}"
INSTALL_MODULE=0

usage() {
    cat <<EOF
Usage: $0 [-i|--install]

Options:
  -i, --install  Install the successfully built module with KernelSU
                 and delete the built ZIP after successful installation.
  -h, --help     Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -i|--install)
            INSTALL_MODULE=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [ "$#" -ne 0 ]; then
    echo "Unexpected positional arguments: $*" >&2
    usage >&2
    exit 2
fi

python3 - "$OUT_DIR" "$ZIP_NAME" <<'PY'
from pathlib import Path
import sys

out_dir = Path(sys.argv[1]).expanduser().resolve()
zip_path = Path(sys.argv[2]).expanduser().resolve()
repo = Path.cwd().resolve()
default_out = (repo / "out").resolve()

if out_dir.exists():
    if out_dir.is_symlink() or not out_dir.is_dir():
        raise SystemExit(f"refusing unsafe module output path: {out_dir}")
    if any(out_dir.iterdir()):
        if out_dir != default_out:
            raise SystemExit("refusing to clean a non-empty custom OUT_DIR; remove it explicitly after review")
        for child in out_dir.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                import shutil
                shutil.rmtree(child)
            else:
                raise SystemExit(f"refusing unusual output entry: {child}")
else:
    out_dir.mkdir(parents=True, exist_ok=False)

try:
    zip_path.relative_to(out_dir)
except ValueError:
    pass
else:
    raise SystemExit("ZIP_NAME must not be inside OUT_DIR")
try:
    zip_path.relative_to(repo)
except ValueError as exc:
    raise SystemExit("ZIP_NAME must stay inside the repository; use manage_source.py for explicit external destinations") from exc
if zip_path.exists():
    if zip_path.is_symlink() or zip_path.is_dir():
        raise SystemExit(f"refusing unsafe ZIP_NAME: {zip_path}")
    zip_path.unlink()
PY

echo "[1/4] Rendering Magisk/KernelSU module..."
PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src" python3 - "$OUT_DIR" "$ZIP_NAME" <<'PY'
from pathlib import Path
import sys
from chrootctl.magisk import MagiskModuleConfig, render_magisk_module, validate_magisk_module, validate_magisk_zip, zip_magisk_module

out_dir = Path(sys.argv[1])
zip_path = Path(sys.argv[2])
render_magisk_module(out_dir, services=None, startup_targets=(), module_config=MagiskModuleConfig())
validate_magisk_module(out_dir)
zip_magisk_module(out_dir, zip_path)
validate_magisk_zip(zip_path)
PY

echo "[2/4] Verifying module tree and executable modes..."
PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src" python3 - "$OUT_DIR" <<'PY'
from pathlib import Path
import sys
from chrootctl.magisk import validate_magisk_module
validate_magisk_module(Path(sys.argv[1]))
PY

echo "[3/4] Reopening and deeply validating final ZIP..."
PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src" python3 - "$ZIP_NAME" <<'PY'
from pathlib import Path
import sys
from chrootctl.magisk import validate_magisk_zip
validate_magisk_zip(Path(sys.argv[1]))
PY

echo "[4/4] Done: $ZIP_NAME"

if [ "$INSTALL_MODULE" -eq 1 ]; then
    echo "[install] Installing module with KernelSU..."

    ZIP_ABS="$(python3 - "$ZIP_NAME" <<'PY_INSTALL_PATH'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY_INSTALL_PATH
)"

    # Quote the path for the Android shell invoked by `su -c`.
    INSTALL_ZIP="$(python3 - "$ZIP_ABS" <<'PY_INSTALL_QUOTE'
import shlex
import sys
print(shlex.quote(sys.argv[1]))
PY_INSTALL_QUOTE
)"

    if su -c "ksud module install $INSTALL_ZIP"; then
        echo "[install] Module installed successfully."
        rm -f -- "$ZIP_ABS"
        echo "[install] Deleted built ZIP: $ZIP_ABS"
        echo "[install] Reboot is required to activate the pending module update."
    else
        status=$?
        echo "[install] KernelSU module installation failed with exit code $status." >&2
        echo "[install] Keeping built ZIP for inspection: $ZIP_ABS" >&2
        exit "$status"
    fi
else
    echo "Flash $ZIP_NAME in Magisk or KernelSU. Pending updates become runtime-active only after reboot activation."
fi
