from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .services import ServiceContainer

DEFAULT_MODULE_ID = "chrootctl-magisk"
DEFAULT_MODULE_NAME = "chrootctl Magisk Module"
DEFAULT_MODULE_VERSION = "1.3.0"
DEFAULT_MODULE_VERSION_CODE = 15
ANDROID_PYDANTIC_CORE_INDEX_URL = "https://eutalix.github.io/android-pydantic-core/"
SUPPORTED_ANDROID_PYDANTIC_CORE_PYTHONS = ("3.9", "3.10", "3.11", "3.12", "3.13")

DEFAULT_PYTHON_DEPENDENCIES = (
    "rich>=13.7.0",
    "PyYAML>=6.0",
    "pydantic>=2.7.0",
)

FORBIDDEN_MODULE_PATH_TOKENS = (
    "chrootctl-web",
    "chrootctl-webui-service",
    "webui.env",
    "webroot",
    "playwright.config.ts",
    "payload/src/chrootctl/web",
)


@dataclass(frozen=True, slots=True)
class MagiskRenderResult:
    output_dir: Path
    files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class MagiskModuleConfig:
    module_id: str = DEFAULT_MODULE_ID
    module_name: str = DEFAULT_MODULE_NAME
    version: str = DEFAULT_MODULE_VERSION
    version_code: int = DEFAULT_MODULE_VERSION_CODE
    helper_name: str = "chrootctl-magisk-helper"
    state_file: str = "config/chrootctl/boot_targets.json"
    package_source_dir: Path | None = None
    python_dependencies: tuple[str, ...] = DEFAULT_PYTHON_DEPENDENCIES
    offline_wheelhouse_dir: Path | None = None

    def helper_path(self) -> str:
        return f"bin/{self.helper_name}"

    def state_path(self) -> str:
        return self.state_file

    def package_root(self) -> Path:
        if self.package_source_dir is not None:
            return self.package_source_dir.resolve()
        return Path(__file__).resolve().parents[1]


def render_magisk_module(
    output_dir: Path,
    *,
    services: ServiceContainer,
    startup_targets: tuple[str, ...],
    helper_command: str = "chrootctl",
    module_config: MagiskModuleConfig | None = None,
) -> MagiskRenderResult:
    del services
    del helper_command

    config = module_config or MagiskModuleConfig()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        Path("module.prop"): _module_prop(config),
        Path("customize.sh"): _customize_sh(),
        Path("post-fs-data.sh"): _post_fs_data_sh(),
        Path("service.sh"): _service_sh(config),
        Path(config.helper_path()): _helper_sh(config),
        Path("bin/chrootctl-python-bootstrap"): _python_bootstrap_sh(),
        Path("system/bin/chrootctl"): _python_entrypoint("chrootctl.cli"),
        Path("system/bin/chrootctl-magisk-helper"): _system_bin_proxy("bin/chrootctl-magisk-helper"),
        Path("system/bin/chrootctl-python-bootstrap"): _system_bin_proxy("bin/chrootctl-python-bootstrap"),
        Path("payload/requirements.txt"): _requirements_txt(config.python_dependencies),
        Path("config/chrootctl/dependency-mode.env"): _dependency_mode_env(),
        Path(config.state_path()): _boot_targets_json(startup_targets),
        Path("wheelhouse/.keep"): "",
    }
    written: list[Path] = []
    for relative_path, content in files.items():
        target = output_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if _is_executable(target, config):
            target.chmod(0o755)
        written.append(target)

    written.extend(_copy_python_payload(output_dir, config.package_root()))
    written.extend(_copy_offline_wheelhouse(output_dir, config.offline_wheelhouse_dir))
    return MagiskRenderResult(output_dir=output_dir, files=tuple(written))


def resolve_startup_targets(
    services: ServiceContainer,
    *,
    selected_names: tuple[str, ...] = (),
    all_installed: bool = False,
) -> tuple[str, ...]:
    if selected_names:
        return tuple(dict.fromkeys(name.strip() for name in selected_names if name.strip()))
    rows = services.chroots().list()
    installed_names = tuple(chroot.name for chroot in rows if chroot.installed)
    if all_installed:
        return installed_names
    return installed_names[:1]


def _is_executable(path: Path, config: MagiskModuleConfig) -> bool:
    return path.suffix == ".sh" or path.name in {config.helper_name, "chrootctl", "chrootctl-python-bootstrap"}


def _copy_python_payload(output_dir: Path, package_root: Path) -> list[Path]:
    payload_root = output_dir / "payload"
    source_root = package_root / "chrootctl"
    if not source_root.exists():
        raise FileNotFoundError(f"missing chrootctl package source at {source_root}")
    target_root = payload_root / "src" / "chrootctl"
    shutil.copytree(
        source_root,
        target_root,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    pyproject = package_root.parent / "pyproject.toml"
    if pyproject.exists():
        shutil.copy2(pyproject, payload_root / "pyproject.toml")
    return [path for path in payload_root.rglob("*") if path.is_file()]



def _copy_offline_wheelhouse(output_dir: Path, wheelhouse_dir: Path | None) -> list[Path]:
    if wheelhouse_dir is None:
        return []
    source = wheelhouse_dir.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"offline wheelhouse does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"offline wheelhouse must be a directory: {source}")
    target = output_dir / "wheelhouse"
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    return [path for path in target.rglob("*") if path.is_file()]


def _module_prop(config: MagiskModuleConfig) -> str:
    return "\n".join(
        (
            f"id={config.module_id}",
            f"name={config.module_name}",
            f"version={config.version}",
            f"versionCode={config.version_code}",
            "author=chrootctl",
            "description=Self-contained Magisk/KSU module for boot startup, helper commands, and the chrootctl Android bridge.",
            "",
        )
    )


def _customize_sh() -> str:
    return """#!/system/bin/sh
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

mkdir -p "$CONFIG_DIR" "$SITE_PACKAGES" "$PIP_TMP_DIR" /data/adb/chrootctl/services /data/adb/chrootctl/run/services /data/adb/chrootctl/logs/services

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
print(sys.version.replace("\\n", " "))
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
out.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
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
set_perm "$MODPATH/system/bin/chrootctl-magisk-helper" 0 0 0755 || ui_print "! Warning: set_perm failed: system/bin/chrootctl-magisk-helper"
set_perm "$MODPATH/system/bin/chrootctl-python-bootstrap" 0 0 0755 || ui_print "! Warning: set_perm failed: system/bin/chrootctl-python-bootstrap"
set_perm "$MODPATH/bin/chrootctl-magisk-helper" 0 0 0755 || ui_print "! Warning: set_perm failed: chrootctl-magisk-helper"
set_perm "$MODPATH/bin/chrootctl-python-bootstrap" 0 0 0755 || ui_print "! Warning: set_perm failed: chrootctl-python-bootstrap"

ui_print "- chrootctl module install configuration complete"
exit 0
"""

def _post_fs_data_sh() -> str:
    return """#!/system/bin/sh
MODDIR=${0%/*}

# Reserved for rare early, blocking setup only.
# Most chrootctl startup work belongs in service.sh.
exit 0
"""


def _service_sh(config: MagiskModuleConfig) -> str:
    helper = config.helper_path()
    state_path = config.state_path()
    return f"""#!/system/bin/sh
MODDIR=${{0%/*}}
HELPER="$MODDIR/{helper}"
STATE_FILE="$MODDIR/{state_path}"
export PATH="$MODDIR/system/bin:/system/bin:/system/xbin:/data/adb/magisk:$PATH"
[ -f "$MODDIR/config/chrootctl/python.env" ] && . "$MODDIR/config/chrootctl/python.env"

[ -x "$HELPER" ] && [ -f "$STATE_FILE" ] && "$HELPER" boot "$STATE_FILE" "$MODDIR" >/dev/null 2>&1 || true
"$MODDIR/system/bin/chrootctl" clipboard daemon start >/dev/null 2>&1 || true
"$MODDIR/system/bin/chrootctl" run --boot >/dev/null 2>&1 || true


exit 0
"""

def _helper_sh(config: MagiskModuleConfig) -> str:
    helper = config.helper_path()
    return f"""#!/system/bin/sh
set -eu

COMMAND=${{1:-}}
STATE_FILE=${{2:-}}
MODDIR=${{3:-}}
CLI="$MODDIR/system/bin/chrootctl"
export PATH="$MODDIR/system/bin:/system/bin:/system/xbin:/data/adb/magisk:$PATH"
[ -f "$MODDIR/config/chrootctl/python.env" ] && . "$MODDIR/config/chrootctl/python.env"
if [ -n "${{PYTHON_LD_LIBRARY_PATH:-}}" ]; then
  export LD_LIBRARY_PATH="$PYTHON_LD_LIBRARY_PATH${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
fi
PYTHON_BIN="${{PYTHON_BIN:-python3}}"

[ -x "$CLI" ] || {{
  echo "missing chrootctl launcher at $CLI" >&2
  exit 1
}}

read_boot_targets() {{
  "$CLI" _magisk-read-boot-targets "$STATE_FILE" 2>/dev/null || "$PYTHON_BIN" - "$STATE_FILE" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
payload = json.loads(state_path.read_text(encoding="utf-8"))
for target in payload.get("startup_targets", []):
    name = str(target).strip()
    if name:
        print(name)
PY
}}

case "$COMMAND" in
  boot)
    read_boot_targets | while IFS= read -r name; do
      [ -n "$name" ] || continue
      "$CLI" --name "$name" mount >/dev/null 2>&1 || true
    done
    ;;
  mount|unmount|start|restart|status|doctor|logs)
    shift
    exec "$CLI" "$COMMAND" "$@"
    ;;
  exec)
    shift
    exec "$CLI" exec "$@"
    ;;
  *)
    echo "unsupported helper command: $COMMAND" >&2
    exit 2
    ;;
esac
"""

def _module_dir_resolver_sh(module_id: str = DEFAULT_MODULE_ID) -> str:
    return f"""resolve_moddir() {{
  _script_dir="${{0%/*}}"
  _candidate="$_script_dir/../.."
  if [ -f "$_candidate/module.prop" ] && grep -q '^id={module_id}$' "$_candidate/module.prop" 2>/dev/null; then
    cd "$_candidate" 2>/dev/null && pwd
    return 0
  fi

  for _candidate in \
    "/data/adb/modules/{module_id}" \
    "/data/adb/modules_update/{module_id}" \
    "/data/adb/ksu/modules/{module_id}" \
    "/data/adb/ksu/modules_update/{module_id}"; do
    if [ -f "$_candidate/module.prop" ] && grep -q '^id={module_id}$' "$_candidate/module.prop" 2>/dev/null; then
      echo "$_candidate"
      return 0
    fi
  done

  echo "$_script_dir/../.."
}}"""


def _system_bin_proxy(relative_target: str) -> str:
    resolver = _module_dir_resolver_sh()
    return f"""#!/system/bin/sh
set -e
set +u

{resolver}
MODDIR="$(resolve_moddir)"
TARGET="$MODDIR/{relative_target}"
export PATH="$MODDIR/system/bin:/system/bin:/system/xbin:/data/adb/magisk:$PATH"

if [ ! -x "$TARGET" ]; then
  echo "missing module executable: $TARGET" >&2
  exit 1
fi

exec "$TARGET" "$@"
"""


def _python_entrypoint(module_name: str) -> str:
    resolver = _module_dir_resolver_sh()
    return f"""#!/system/bin/sh
set -e
set +u

{resolver}
MODDIR="$(resolve_moddir)"
SITE_PACKAGES="$MODDIR/python/site-packages"
PAYLOAD_SRC="$MODDIR/payload/src"
[ -f "$MODDIR/config/chrootctl/python.env" ] && . "$MODDIR/config/chrootctl/python.env"
# Always recompute module-local import paths from the active module directory.
SITE_PACKAGES="$MODDIR/python/site-packages"
PAYLOAD_SRC="$MODDIR/payload/src"
PYTHONPATH=""

python_candidate_runs() {{
  _candidate_bin="$1"
  _candidate_lib="$2"
  [ -n "$_candidate_bin" ] || return 1
  [ -x "$_candidate_bin" ] || return 1
  if [ -n "$_candidate_lib" ] && [ ! -d "$_candidate_lib" ]; then
    return 1
  fi
  if [ -n "$_candidate_lib" ]; then
    LD_LIBRARY_PATH="$_candidate_lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}" "$_candidate_bin" -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1
  else
    "$_candidate_bin" -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1
  fi
}}

try_python_candidate() {{
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
}}

select_python_runtime() {{
  PYTHON_PATH_BIN="$(command -v python3 2>/dev/null || true)"
  for _candidate_bin in "${{CHROOTCTL_PYTHON_BIN:-}}" /system/bin/python3 "$PYTHON_PATH_BIN" /data/data/com.termux/files/usr/bin/python3 /data/adb/py2droid/usr/bin/python3 "${{PYTHON_BIN:-}}"; do
    try_python_candidate "$_candidate_bin" && return 0
  done
  return 1
}}

select_python_runtime || {{
  echo "no runnable python3 found for chrootctl" >&2
  exit 1
}}
if [ -n "${{PYTHON_LD_LIBRARY_PATH:-}}" ]; then
  export LD_LIBRARY_PATH="$PYTHON_LD_LIBRARY_PATH${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
fi

SITE_PACKAGES="$MODDIR/python/site-packages"
PAYLOAD_SRC="$MODDIR/payload/src"
export PYTHONPATH="$PAYLOAD_SRC:$SITE_PACKAGES"

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import chrootctl
PY
then
  echo "chrootctl package is not importable" >&2
  echo "MODDIR=$MODDIR" >&2
  echo "PYTHON_BIN=$PYTHON_BIN" >&2
  echo "PYTHONPATH=$PYTHONPATH" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m {module_name} "$@"
"""

def _python_bootstrap_sh() -> str:
    return """#!/system/bin/sh
set -e
set +u

MODDIR=${1:-${0%/*}/..}
CONFIG_DIR="$MODDIR/config/chrootctl"
SITE_PACKAGES="$MODDIR/python/site-packages"
PAYLOAD_SRC="$MODDIR/payload/src"
DETECTION_FILE="$CONFIG_DIR/python-detection.txt"
READY_FILE="$CONFIG_DIR/dependencies.ready"
BOOTSTRAP_LOG="$CONFIG_DIR/dependency-bootstrap.log"
PIP_TMP_DIR="$MODDIR/tmp"

mkdir -p "$CONFIG_DIR" "$SITE_PACKAGES" "$PIP_TMP_DIR" /data/adb/chrootctl/services /data/adb/chrootctl/run/services /data/adb/chrootctl/logs/services

[ -f "$CONFIG_DIR/python.env" ] && . "$CONFIG_DIR/python.env"
# Always recompute module-local import paths from the active MODDIR.
SITE_PACKAGES="$MODDIR/python/site-packages"
PAYLOAD_SRC="$MODDIR/payload/src"
DETECTION_FILE="$CONFIG_DIR/python-detection.txt"
READY_FILE="$CONFIG_DIR/dependencies.ready"
BOOTSTRAP_LOG="$CONFIG_DIR/dependency-bootstrap.log"
PIP_TMP_DIR="$MODDIR/tmp"

log() {
  echo "[chrootctl-python-bootstrap] $1"
}

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
  PYTHON_PATH_BIN="$(command -v python3 2>/dev/null || true)"
  for _candidate_bin in "${CHROOTCTL_PYTHON_BIN:-}" /system/bin/python3 "$PYTHON_PATH_BIN" /data/data/com.termux/files/usr/bin/python3 /data/adb/py2droid/usr/bin/python3 "${PYTHON_BIN:-}"; do
    try_python_candidate "$_candidate_bin" && return 0
  done
  return 1
}

select_python_runtime || {
  log "no runnable python3 found"
  exit 1
}
if [ -n "${PYTHON_LD_LIBRARY_PATH:-}" ]; then
  export LD_LIBRARY_PATH="$PYTHON_LD_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

export PYTHONPATH="$PAYLOAD_SRC:$SITE_PACKAGES"
export TMPDIR="$PIP_TMP_DIR"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_ROOT_USER_ACTION=ignore

log "using static Python environment: $PYTHON_BIN"
log "python library path: ${PYTHON_LD_LIBRARY_PATH:-default linker path}"
cat >"$CONFIG_DIR/python.env" <<EOF
PYTHON_BIN="$PYTHON_BIN"
PYTHON_LD_LIBRARY_PATH="$PYTHON_LD_LIBRARY_PATH"
SITE_PACKAGES="$SITE_PACKAGES"
PAYLOAD_SRC="$PAYLOAD_SRC"
PYTHONPATH="$PAYLOAD_SRC:$SITE_PACKAGES"
EOF

validate_static_environment() {
  "$PYTHON_BIN" - "$DETECTION_FILE" <<'PY'
import importlib.util
import sys
from pathlib import Path

out = Path(sys.argv[1])
required = (
    ("rich", "rich"),
    ("yaml", "PyYAML"),
    ("pydantic", "pydantic"),
    ("pydantic_core", "pydantic-core"),
)
lines = [
    f"python_executable={sys.executable}",
    f"python_version={sys.version.replace(chr(10), ' ')}",
    f"python_prefix={sys.prefix}",
    "dependency_mode=static-python-env",
]
problems = []
for module_name, package_name in required:
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception as exc:
        spec = None
        problems.append(f"{package_name}:find_error:{exc}")
    location = getattr(spec, "origin", None) if spec else None
    if spec is None:
        problems.append(f"{package_name}:missing")
    lines.append(f"module.{module_name}={'found' if spec else 'missing'} {location or ''}".rstrip())

try:
    from pydantic import TypeAdapter  # noqa: F401
except Exception as exc:
    problems.append(f"pydantic:incompatible:{exc}")

if problems:
    lines.append("dependency_status=broken")
    lines.extend(f"problem={problem}" for problem in problems)
else:
    lines.append("dependency_status=ready")

out.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
if problems:
    print(" ".join(problems))
    raise SystemExit(1)
PY
}

if validate_static_environment; then
  log "static Python environment is ready"
  date +%s >"$READY_FILE"
  rm -f "$BOOTSTRAP_LOG" 2>/dev/null || true
  exit 0
fi

log "static Python environment is missing required modules"
{
  echo "mode=static-python-env"
  echo "python=$PYTHON_BIN"
  echo "pythondir=${PYTHON_LD_LIBRARY_PATH:-}"
  echo "payload=$PAYLOAD_SRC"
  echo "site_packages=$SITE_PACKAGES"
  echo "hint=Fix the static Python module environment; chrootctl no longer installs or repairs Python packages."
  echo "required=rich PyYAML pydantic pydantic-core"
  grep '^problem=' "$DETECTION_FILE" 2>/dev/null || true
} >"$BOOTSTRAP_LOG"
exit 1
"""


def _dependency_mode_env() -> str:
    return "\n".join(
        (
            'DEPENDENCY_MODE="static-python-env"',
            'DEPENDENCY_INSTALL_PHASE="none"',
            'DEPENDENCY_NETWORK="disabled"',
            'DEPENDENCY_REPAIR="disabled"',
            "",
        )
    )




def _requirements_txt(requirements: tuple[str, ...]) -> str:
    return "\n".join((*requirements, ""))



def _boot_targets_json(startup_targets: tuple[str, ...]) -> str:
    payload = {
        "startup_targets": list(startup_targets),
    }
    return json.dumps(payload, indent=2) + "\n"



def validate_magisk_module(output_dir: Path) -> tuple[Path, ...]:
    required_paths = (
        Path("module.prop"),
        Path("customize.sh"),
        Path("post-fs-data.sh"),
        Path("service.sh"),
        Path("bin/chrootctl-magisk-helper"),
        Path("bin/chrootctl-python-bootstrap"),
        Path("system/bin/chrootctl"),
        Path("payload/src/chrootctl"),
        Path("config/chrootctl/boot_targets.json"),
        Path("config/chrootctl/dependency-mode.env"),
        Path("wheelhouse/.keep"),
    )
    missing = tuple(path for path in required_paths if not (output_dir / path).exists())
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"invalid Magisk module output; missing: {formatted}")
    forbidden = tuple(
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
        and any(token in path.relative_to(output_dir).as_posix() for token in FORBIDDEN_MODULE_PATH_TOKENS)
    )
    if forbidden:
        formatted = ", ".join(sorted(forbidden))
        raise FileNotFoundError(f"invalid Magisk module output; retired WebUI artifact returned: {formatted}")
    return tuple(output_dir / path for path in required_paths)


def zip_magisk_module(output_dir: Path, zip_path: Path) -> Path:
    validate_magisk_module(output_dir)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output_dir).as_posix())
    return zip_path

