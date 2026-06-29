#!/system/bin/sh
set -e
set +u

SKIPMOUNT=false
PROPFILE=true
POSTFSDATA=true
LATESTARTSERVICE=true

CONFIG_DIR="$MODPATH/config/chrootctl"
SITE_PACKAGES="$MODPATH/python/site-packages"
PAYLOAD_SRC="$MODPATH/payload/src"
PIP_TMP_DIR="$MODPATH/tmp"

mkdir -p "$CONFIG_DIR" "$SITE_PACKAGES" "$PIP_TMP_DIR"

ui_print "- Checking python3"
PYTHON_PATH_BIN="$(command -v python3 2>/dev/null || true)"
PYTHON_BIN=""
PYTHON_LD_LIBRARY_PATH=""

python_candidate_runs() {
  _candidate_bin="$1"
  _candidate_lib="$2"

  [ -n "$_candidate_bin" ] || return 1
  [ -x "$_candidate_bin" ] || return 1
  if [ -n "$_candidate_lib" ] && [ ! -d "$_candidate_lib" ]; then
    return 1
  fi

  if [ -n "$_candidate_lib" ]; then
    LD_LIBRARY_PATH="$_candidate_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$_candidate_bin" -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1
  else
    "$_candidate_bin" -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1
  fi
}

try_python_candidate() {
  _candidate_bin="$1"
  [ -n "$_candidate_bin" ] || return 1
  [ -x "$_candidate_bin" ] || return 1

  _candidate_prefix="$(dirname "$(dirname "$_candidate_bin")")"
  for _candidate_lib in "" "$_candidate_prefix/lib" /system/lib64 /system/lib /data/data/com.termux/files/usr/lib /data/adb/py2droid/usr/lib; do
    if python_candidate_runs "$_candidate_bin" "$_candidate_lib"; then
      PYTHON_BIN="$_candidate_bin"
      PYTHON_LD_LIBRARY_PATH="$_candidate_lib"
      return 0
    fi
  done

  return 1
}

select_python_runtime() {
  for _candidate_bin in "${CHROOTCTL_PYTHON_BIN:-}" /system/bin/python3 "$PYTHON_PATH_BIN" /data/data/com.termux/files/usr/bin/python3 /data/adb/py2droid/usr/bin/python3; do
    try_python_candidate "$_candidate_bin" && return 0
  done
  return 1
}

select_python_runtime || abort "! no runnable python3 found. Checked CHROOTCTL_PYTHON_BIN, /system/bin/python3, PATH python3, Termux, and py2droid."
if [ -n "$PYTHON_LD_LIBRARY_PATH" ]; then
  export LD_LIBRARY_PATH="$PYTHON_LD_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

PYTHON_VERSION="$("$PYTHON_BIN" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
PYTHON_FULL_VERSION="$("$PYTHON_BIN" - <<'PY'
import sys
print(sys.version.replace("\n", " "))
PY
)"
PYTHON_PREFIX="$("$PYTHON_BIN" - <<'PY'
import sys
print(sys.prefix)
PY
)"
PYTHON_EXECUTABLE="$("$PYTHON_BIN" - <<'PY'
import sys
print(sys.executable)
PY
)"
PIP_VERSION="$("$PYTHON_BIN" -m pip --version 2>/dev/null || true)"
PIP_LOCATION="$("$PYTHON_BIN" - <<'PY'
try:
    import pip
    print(getattr(pip, "__file__", "unavailable"))
except Exception as exc:
    print(f"unavailable: {exc}")
PY
)"

ui_print "- Python PATH entry: ${PYTHON_PATH_BIN:-unavailable}"
ui_print "- Python selected binary: $PYTHON_BIN"
ui_print "- Python executable: $PYTHON_EXECUTABLE"
ui_print "- Python runtime used by module: $PYTHON_BIN"
ui_print "- Python library path: ${PYTHON_LD_LIBRARY_PATH:-default linker path}"
ui_print "- Python version: $PYTHON_FULL_VERSION"
ui_print "- Python prefix: $PYTHON_PREFIX"
ui_print "- pip: ${PIP_VERSION:-unavailable}"
ui_print "- pip module: $PIP_LOCATION"
ui_print "- No Python dependencies are installed during Magisk/KSU install"
ui_print "- Dependencies are checked against the static Python environment at first boot"

export PYTHONPATH="$PAYLOAD_SRC:$SITE_PACKAGES"
export TMPDIR="$PIP_TMP_DIR"
export PIP_CACHE_DIR="$PIP_TMP_DIR/pip-cache"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_ROOT_USER_ACTION=ignore

cat >"$CONFIG_DIR/python.env" <<EOF
PYTHON_PATH_BIN="$PYTHON_PATH_BIN"
PYTHON_BIN="$PYTHON_BIN"
PYTHON_LD_LIBRARY_PATH="$PYTHON_LD_LIBRARY_PATH"
PYTHON_VERSION="$PYTHON_VERSION"
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE"
PYTHON_PREFIX="$PYTHON_PREFIX"
# Runtime paths are intentionally recomputed from the active module directory.
# Do not persist install-time /data/adb/modules_update paths here.
EOF

ui_print "- Checking already-installed Python modules"
set +e
"$PYTHON_BIN" - "$CONFIG_DIR/python-detection.txt" <<'PY'
import importlib.util
import sys
from pathlib import Path

out = Path(sys.argv[1])
modules = (
    "rich",
    "yaml",
    "fastapi",
    "jinja2",
    "uvicorn",
    "pydantic",
    "pydantic_core",
)
lines = [
    f"python_executable={sys.executable}",
    f"python_version={sys.version.replace(chr(10), ' ')}",
    f"python_prefix={sys.prefix}",
    "install_phase=static-python-env",
]
missing = []
for name in modules:
    try:
        spec = importlib.util.find_spec(name)
    except Exception as exc:
        spec = None
        lines.append(f"module.{name}=error {exc}")
        missing.append(name)
        continue
    location = getattr(spec, "origin", None) if spec else None
    status = "found" if spec else "missing"
    if not spec:
        missing.append(name)
    lines.append(f"module.{name}={status} {location or ''}".rstrip())
lines.append("missing=" + " ".join(missing))
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
if missing:
    print("missing=" + " ".join(missing))
else:
    print("missing=none")
PY
DETECTION_STATUS=$?
set -e
if [ "$DETECTION_STATUS" -eq 0 ]; then
  DETECTED_MISSING="$(grep '^missing=' "$CONFIG_DIR/python-detection.txt" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  ui_print "- Python module detection saved"
  ui_print "- Missing Python modules: ${DETECTED_MISSING:-unknown}"
else
  ui_print "! Warning: Python module detection failed; first boot will retry"
  {
    echo "install_phase=static-python-env"
    echo "detection=failed"
  } >"$CONFIG_DIR/python-detection.txt" 2>/dev/null || true
fi

rm -rf "$PIP_TMP_DIR" 2>/dev/null || true
mkdir -p "$PIP_TMP_DIR" 2>/dev/null || true

ui_print "- Applying module permissions"
set_perm_recursive "$MODPATH" 0 0 0755 0644 || ui_print "! Warning: set_perm_recursive failed"
set_perm "$MODPATH/system/bin/chrootctl" 0 0 0755 || ui_print "! Warning: set_perm failed: system/bin/chrootctl"
set_perm "$MODPATH/system/bin/chrootctl-web" 0 0 0755 || ui_print "! Warning: set_perm failed: system/bin/chrootctl-web"
set_perm "$MODPATH/system/bin/chrootctl-magisk-helper" 0 0 0755 || ui_print "! Warning: set_perm failed: system/bin/chrootctl-magisk-helper"
set_perm "$MODPATH/system/bin/chrootctl-python-bootstrap" 0 0 0755 || ui_print "! Warning: set_perm failed: system/bin/chrootctl-python-bootstrap"
set_perm "$MODPATH/system/bin/chrootctl-webui-service" 0 0 0755 || ui_print "! Warning: set_perm failed: system/bin/chrootctl-webui-service"
set_perm "$MODPATH/bin/chrootctl-magisk-helper" 0 0 0755 || ui_print "! Warning: set_perm failed: chrootctl-magisk-helper"
set_perm "$MODPATH/bin/chrootctl-python-bootstrap" 0 0 0755 || ui_print "! Warning: set_perm failed: chrootctl-python-bootstrap"
set_perm "$MODPATH/bin/chrootctl-webui-service" 0 0 0755 || ui_print "! Warning: set_perm failed: chrootctl-webui-service"

ui_print "- chrootctl module install configuration complete"
exit 0
