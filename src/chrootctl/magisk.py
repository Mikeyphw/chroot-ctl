from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .native_runtime import (
    DEFAULT_NATIVE_RUNTIME_ABI,
    DEFAULT_NATIVE_RUNTIME_BUILD_ROOT,
    DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
    validate_native_runtime_artifact,
)

if TYPE_CHECKING:
    from .services import ServiceContainer

DEFAULT_MODULE_ID = "chrootctl-magisk"
DEFAULT_MODULE_NAME = "chrootctl Magisk Module"
DEFAULT_MODULE_VERSION = "1.3.0"
DEFAULT_MODULE_VERSION_CODE = 15
BRIDGE_PROTOCOL_VERSION = 1
PYTHON_PACKAGE_VERSION = "0.11.0"
ANDROID_APP_VERSION_NAME = "0.1.0-phase29"
ANDROID_APP_VERSION_CODE = 1
FORBIDDEN_MODULE_PATH_TOKENS = (
    "chrootctl-web",
    "chrootctl-webui-service",
    "webui.env",
    "webroot",
    "playwright.config.ts",
)
FORBIDDEN_MODULE_BASENAMES = {
    ".DS_Store",
    "Thumbs.db",
}
FORBIDDEN_MODULE_SUFFIXES = (
    ".bak",
    ".backup",
    ".orig",
    ".rej",
    ".swp",
    ".swo",
    "~",
)
ALLOWED_MODULE_TOP_LEVEL = {
    "module.prop",
    "customize.sh",
    "post-fs-data.sh",
    "service.sh",
    "bin",
    "system",
    "config",
    "runtime",
}
NATIVE_RUNTIME_MODULE_ROOT = Path("runtime") / DEFAULT_NATIVE_RUNTIME_ABI
NATIVE_RUNTIME_MANIFEST_PATH = NATIVE_RUNTIME_MODULE_ROOT / "runtime-manifest.json"
NATIVE_RUNTIME_ENTRYPOINT_PATH = NATIVE_RUNTIME_MODULE_ROOT / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
MODULE_MAX_FILE_BYTES = 128 * 1024 * 1024
MODULE_MAX_TOTAL_BYTES = 512 * 1024 * 1024
REQUIRED_EXECUTABLE_PATHS = {
    "customize.sh",
    "post-fs-data.sh",
    "service.sh",
    "bin/chrootctl-magisk-helper",
    "system/bin/chrootctl",
    "system/bin/chrootctl-magisk-helper",
    NATIVE_RUNTIME_ENTRYPOINT_PATH.as_posix(),
}
REQUIRED_MODULE_PATHS = {
    "module.prop",
    "customize.sh",
    "post-fs-data.sh",
    "service.sh",
    "bin/chrootctl-magisk-helper",
    "system/bin/chrootctl",
    "system/bin/chrootctl-magisk-helper",
    "config/chrootctl/boot_targets.json",
    "config/chrootctl/compatibility-manifest.json",
    NATIVE_RUNTIME_MANIFEST_PATH.as_posix(),
    NATIVE_RUNTIME_ENTRYPOINT_PATH.as_posix(),
}
_ALLOWED_MODULE_DIRS = {
    "bin",
    "system",
    "system/bin",
    "config",
    "config/chrootctl",
    "runtime",
    NATIVE_RUNTIME_MODULE_ROOT.as_posix(),
    (NATIVE_RUNTIME_MODULE_ROOT / "chrootctl.dist").as_posix(),
}


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
    native_runtime_dir: Path | None = None

    def helper_path(self) -> str:
        return f"bin/{self.helper_name}"

    def state_path(self) -> str:
        return self.state_file

    def package_root(self) -> Path:
        if self.package_source_dir is not None:
            return self.package_source_dir.resolve()
        return Path(__file__).resolve().parents[1]

    def native_runtime_root(self) -> Path:
        if self.native_runtime_dir is not None:
            return self.native_runtime_dir.expanduser().absolute()
        override = os.environ.get("CHROOTCTL_NATIVE_RUNTIME_DIR", "").strip()
        if override:
            return Path(override).expanduser().absolute()
        return (self.package_root().parent / DEFAULT_NATIVE_RUNTIME_BUILD_ROOT / DEFAULT_NATIVE_RUNTIME_ABI).absolute()


def render_magisk_module(
    output_dir: Path,
    *,
    services: ServiceContainer | None,
    startup_targets: tuple[str, ...],
    helper_command: str = "chrootctl",
    module_config: MagiskModuleConfig | None = None,
) -> MagiskRenderResult:
    del services
    del helper_command

    config = module_config or MagiskModuleConfig()
    _validate_release_identity_sources(config)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.is_symlink():
        raise ValueError(f"refusing to render module into symlinked output directory: {output_dir}")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError(f"module output must be a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise FileExistsError(f"refusing to replace non-empty module output directory: {output_dir}")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)

    files = {
        Path("module.prop"): _module_prop(config),
        Path("customize.sh"): _customize_sh(),
        Path("post-fs-data.sh"): _post_fs_data_sh(),
        Path("service.sh"): _service_sh(config),
        Path(config.helper_path()): _helper_sh(config),
        Path("system/bin/chrootctl"): _native_entrypoint(),
        Path("system/bin/chrootctl-magisk-helper"): _system_bin_proxy("bin/chrootctl-magisk-helper"),
        Path("config/chrootctl/compatibility-manifest.json"): _compatibility_manifest_json(config),
        Path(config.state_path()): _boot_targets_json(startup_targets),
    }
    written: list[Path] = []
    for relative_path, content in files.items():
        target = output_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if _is_executable(target, config):
            target.chmod(0o755)
        written.append(target)

    written.extend(_copy_native_runtime(output_dir, config))
    return MagiskRenderResult(output_dir=output_dir, files=tuple(written))


def resolve_startup_targets(
    services: ServiceContainer,
    *,
    selected_names: tuple[str, ...] = (),
    all_installed: bool = False,
) -> tuple[str, ...]:
    rows = services.chroots().list()
    installed_names = tuple(sorted(chroot.name for chroot in rows if chroot.installed))
    if selected_names:
        selected = tuple(dict.fromkeys(name.strip() for name in selected_names if name.strip()))
        installed = set(installed_names)
        unknown = tuple(name for name in selected if name not in installed)
        if unknown:
            raise ValueError("module startup targets must be installed chroots: " + ", ".join(unknown))
        return selected
    if all_installed:
        return installed_names
    return ()


def _is_executable(path: Path, config: MagiskModuleConfig) -> bool:
    return path.suffix == ".sh" or path.name in {config.helper_name, "chrootctl"}


def _forbidden_module_relative_path(relative: Path) -> bool:
    text = relative.as_posix()
    if relative.name in FORBIDDEN_MODULE_BASENAMES:
        return True
    if any(relative.name.endswith(suffix) for suffix in FORBIDDEN_MODULE_SUFFIXES):
        return True
    if any(part in {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"} for part in relative.parts):
        return True
    return any(token in text for token in FORBIDDEN_MODULE_PATH_TOKENS)


def _copy_native_runtime(output_dir: Path, config: MagiskModuleConfig) -> list[Path]:
    source_root = config.native_runtime_root()
    validate_native_runtime_artifact(
        source_root,
        expected_abi=DEFAULT_NATIVE_RUNTIME_ABI,
        package_version=PYTHON_PACKAGE_VERSION,
        bridge_protocol_version=BRIDGE_PROTOCOL_VERSION,
    )
    target_root = output_dir / NATIVE_RUNTIME_MODULE_ROOT
    if target_root.exists():
        raise FileExistsError(f"native runtime module destination already exists: {target_root}")
    written: list[Path] = []
    target_root.mkdir(parents=True, exist_ok=False)
    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        if source.is_symlink():
            raise ValueError(f"refusing symlink in native runtime artifact: {source}")
        target = target_root / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not source.is_file():
            raise ValueError(f"refusing non-regular native runtime artifact: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(target)
    validate_native_runtime_artifact(
        target_root,
        expected_abi=DEFAULT_NATIVE_RUNTIME_ABI,
        package_version=PYTHON_PACKAGE_VERSION,
        bridge_protocol_version=BRIDGE_PROTOCOL_VERSION,
    )
    return written


def _validate_release_identity_sources(config: MagiskModuleConfig) -> None:
    repo = config.package_root().parent
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file() or pyproject.is_symlink():
        raise FileNotFoundError(f"missing safe pyproject.toml for module release identity: {pyproject}")
    pyproject_text = pyproject.read_text(encoding="utf-8")
    version_match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', pyproject_text)
    if version_match is None or version_match.group(1) != PYTHON_PACKAGE_VERSION:
        raise ValueError("Python package version does not match module compatibility identity")

    gradle = repo / "android/app/build.gradle.kts"
    if not gradle.is_file() or gradle.is_symlink():
        raise FileNotFoundError(f"missing safe Android build identity source: {gradle}")
    gradle_text = gradle.read_text(encoding="utf-8")
    name_match = re.search(r'versionName\s*=\s*"([^"]+)"', gradle_text)
    code_match = re.search(r'versionCode\s*=\s*(\d+)', gradle_text)
    if name_match is None or name_match.group(1) != ANDROID_APP_VERSION_NAME:
        raise ValueError("Android versionName does not match module compatibility identity")
    if code_match is None or int(code_match.group(1)) != ANDROID_APP_VERSION_CODE:
        raise ValueError("Android versionCode does not match module compatibility identity")

    release_manifest = repo / "docs/release/compatibility-manifest.json"
    if not release_manifest.is_file() or release_manifest.is_symlink():
        raise FileNotFoundError(f"missing safe release compatibility manifest: {release_manifest}")
    payload = json.loads(release_manifest.read_text(encoding="utf-8"))
    if payload != _compatibility_manifest_payload(config):
        raise ValueError("release compatibility manifest does not match module/Python/Android identity")


def _compatibility_manifest_payload(config: MagiskModuleConfig) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "project": "chrootctl",
        "bridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        "pythonPackage": {"name": "chrootctl", "version": PYTHON_PACKAGE_VERSION},
        "androidApp": {
            "applicationId": "com.mikeyphw.chrootctl",
            "versionName": ANDROID_APP_VERSION_NAME,
            "versionCode": ANDROID_APP_VERSION_CODE,
            "minimumSupportedModuleVersionCode": config.version_code,
        },
        "module": {
            "id": config.module_id,
            "version": config.version,
            "versionCode": config.version_code,
            "minimumSupportedBridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        },
    }


def _compatibility_manifest_json(config: MagiskModuleConfig) -> str:
    return json.dumps(_compatibility_manifest_payload(config), indent=2, sort_keys=True) + "\n"


def _module_prop(config: MagiskModuleConfig) -> str:
    return "\n".join(
        (
            f"id={config.module_id}",
            f"name={config.module_name}",
            f"version={config.version}",
            f"versionCode={config.version_code}",
            "author=chrootctl",
            "description=Self-contained chrootctl Magisk/KernelSU runtime with a bundled Android native userspace.",
            "",
        )
    )


def _customize_sh() -> str:
    return """#!/system/bin/sh
# customize.sh is sourced by the Magisk/KernelSU module installer.
# Do not enable set -e or set -u here: shell options would leak into the
# parent installer and can break installer-provided helper functions.

SKIPMOUNT=false
PROPFILE=true
POSTFSDATA=true
LATESTARTSERVICE=true

CONFIG_DIR="$MODPATH/config/chrootctl"
STATE_ROOT="/data/adb/chrootctl"
for _state_path in "$STATE_ROOT" "$STATE_ROOT/services" "$STATE_ROOT/run" "$STATE_ROOT/run/services" "$STATE_ROOT/logs" "$STATE_ROOT/logs/services"; do
  [ ! -L "$_state_path" ] || abort "! refusing symlinked module state path: $_state_path"
done
mkdir -p "$CONFIG_DIR" \
  "$STATE_ROOT/services" "$STATE_ROOT/run/services" "$STATE_ROOT/logs/services" \
  || abort "! failed to create module state directories"
for _state_path in "$STATE_ROOT" "$STATE_ROOT/services" "$STATE_ROOT/run" "$STATE_ROOT/run/services" "$STATE_ROOT/logs" "$STATE_ROOT/logs/services"; do
  [ -d "$_state_path" ] && [ ! -L "$_state_path" ] || abort "! unsafe module state directory: $_state_path"
done
chmod 0700 "$STATE_ROOT" "$STATE_ROOT/services" "$STATE_ROOT/run" "$STATE_ROOT/run/services" "$STATE_ROOT/logs" "$STATE_ROOT/logs/services" \
  || abort "! failed to secure module state directories"

ui_print "- Checking bundled native chrootctl runtime"
case "$(uname -m 2>/dev/null || true)" in
  aarch64|arm64) RUNTIME_ABI="arm64-v8a" ;;
  *) abort "! unsupported Android host architecture for bundled chrootctl runtime" ;;
esac
RUNTIME_ROOT="$MODPATH/runtime/$RUNTIME_ABI"
RUNTIME_MANIFEST="$RUNTIME_ROOT/runtime-manifest.json"
RUNTIME_BIN="$RUNTIME_ROOT/chrootctl"
[ -d "$RUNTIME_ROOT" ] && [ ! -L "$RUNTIME_ROOT" ] || abort "! bundled native runtime directory is missing or unsafe"
[ -f "$RUNTIME_MANIFEST" ] && [ ! -L "$RUNTIME_MANIFEST" ] || abort "! bundled native runtime manifest is missing or unsafe"
[ -f "$RUNTIME_BIN" ] && [ ! -L "$RUNTIME_BIN" ] || abort "! bundled native chrootctl executable is missing or unsafe"

ui_print "- Applying module permissions"
SYSTEM_FILE_CONTEXT="u:object_r:system_file:s0"

set_perm_recursive "$MODPATH" 0 0 0755 0644 "$SYSTEM_FILE_CONTEXT" \
  || abort "! failed to set module permissions"

set_perm_recursive "$CONFIG_DIR" 0 0 0700 0600 "$SYSTEM_FILE_CONTEXT" \
  || abort "! failed to secure module runtime configuration"
for _file in \
  "$MODPATH/customize.sh" \
  "$MODPATH/post-fs-data.sh" \
  "$MODPATH/service.sh" \
  "$MODPATH/system/bin/chrootctl" \
  "$MODPATH/system/bin/chrootctl-magisk-helper" \
  "$MODPATH/bin/chrootctl-magisk-helper" \
  "$RUNTIME_BIN"; do
  set_perm "$_file" 0 0 0755 "$SYSTEM_FILE_CONTEXT" \
    || abort "! failed to set executable permission: $_file"
done

ui_print "- chrootctl module install checks complete; bundled runtime requires no external Python environment"
"""


def _post_fs_data_sh() -> str:
    return """#!/system/bin/sh
set -eu
MODDIR=${0%/*}
STATE_ROOT=/data/adb/chrootctl
[ ! -L "$STATE_ROOT" ] && [ ! -L "$STATE_ROOT/logs" ] || { echo "unsafe chrootctl state path" >&2; exit 1; }
mkdir -p "$STATE_ROOT" "$STATE_ROOT/logs"
[ -d "$STATE_ROOT" ] && [ ! -L "$STATE_ROOT" ] && [ -d "$STATE_ROOT/logs" ] && [ ! -L "$STATE_ROOT/logs" ] || { echo "unsafe chrootctl state directory" >&2; exit 1; }
chmod 0700 "$STATE_ROOT" "$STATE_ROOT/logs"
exit 0
"""


def _identity_lock_sh() -> str:
    return r"""proc_start_time() {
  _lock_pid="$1"
  [ -n "$_lock_pid" ] && [ -r "/proc/$_lock_pid/stat" ] || return 1
  awk '{print $22}' "/proc/$_lock_pid/stat" 2>/dev/null
}

current_boot_id() {
  [ -r /proc/sys/kernel/random/boot_id ] || return 1
  cat /proc/sys/kernel/random/boot_id
}

write_lock_owner() {
  _lock_path="$1"
  _lock_boot="$(current_boot_id)" || return 1
  _lock_start="$(proc_start_time "$$")" || return 1
  printf '%s %s %s\n' "$$" "$_lock_boot" "$_lock_start" >"$_lock_path/owner" || return 1
  chmod 0600 "$_lock_path/owner" || return 1
}

acquire_identity_lock() {
  _lock_path="$1"
  _lock_parent="$2"
  case "$_lock_path" in
    "$_lock_parent"/*) ;;
    *) return 1 ;;
  esac
  [ -d "$_lock_parent" ] && [ ! -L "$_lock_parent" ] || return 1
  if mkdir "$_lock_path" 2>/dev/null; then
    chmod 0700 "$_lock_path" || { rmdir "$_lock_path" 2>/dev/null || true; return 1; }
    write_lock_owner "$_lock_path" || { rm -rf "$_lock_path"; return 1; }
    return 0
  fi

  # Give a concurrent owner a chance to publish its identity before deciding
  # that an inherited lock is stale.
  sleep 1
  _owner_pid=""; _owner_boot=""; _owner_start=""
  if [ -f "$_lock_path/owner" ] && [ ! -L "$_lock_path/owner" ]; then
    IFS=' ' read -r _owner_pid _owner_boot _owner_start <"$_lock_path/owner" || true
  fi
  _current_boot="$(current_boot_id 2>/dev/null || true)"
  _current_start="$(proc_start_time "$_owner_pid" 2>/dev/null || true)"
  if [ -n "$_owner_pid" ] && [ -n "$_current_boot" ] && [ "$_owner_boot" = "$_current_boot" ] \
    && [ -n "$_owner_start" ] && [ "$_owner_start" = "$_current_start" ]; then
    return 2
  fi

  [ ! -L "$_lock_path" ] || return 1
  rm -rf "$_lock_path"
  mkdir "$_lock_path" 2>/dev/null || return 2
  chmod 0700 "$_lock_path" || { rm -rf "$_lock_path"; return 1; }
  write_lock_owner "$_lock_path" || { rm -rf "$_lock_path"; return 1; }
  return 0
}

release_identity_lock() {
  _lock_path="$1"
  [ -d "$_lock_path" ] && [ ! -L "$_lock_path" ] || return 0
  _owner_pid=""; _owner_boot=""; _owner_start=""
  if [ -f "$_lock_path/owner" ] && [ ! -L "$_lock_path/owner" ]; then
    IFS=' ' read -r _owner_pid _owner_boot _owner_start <"$_lock_path/owner" || true
  fi
  _self_boot="$(current_boot_id 2>/dev/null || true)"
  _self_start="$(proc_start_time "$$" 2>/dev/null || true)"
  if [ "$_owner_pid" = "$$" ] && [ "$_owner_boot" = "$_self_boot" ] && [ "$_owner_start" = "$_self_start" ]; then
    rm -rf "$_lock_path"
  fi
}
"""


def _service_sh(config: MagiskModuleConfig) -> str:
    helper = config.helper_path()
    state_path = config.state_path()
    lock_helpers = _identity_lock_sh()
    return f"""#!/system/bin/sh
set -eu
RAW_MODDIR=${{0%/*}}
EXPECTED="/data/adb/modules/{config.module_id}"
[ -d "$EXPECTED" ] && [ ! -L "$EXPECTED" ] || {{ echo "refusing missing or symlinked active module" >&2; exit 1; }}
MODDIR="$(cd "$RAW_MODDIR" && pwd -P)"
[ "$MODDIR" = "$EXPECTED" ] || {{ echo "refusing module service outside active module" >&2; exit 1; }}
[ ! -e "$MODDIR/disable" ] && [ ! -e "$MODDIR/remove" ] || {{ echo "module is disabled or pending removal" >&2; exit 1; }}
HELPER="$MODDIR/{helper}"
CLI="$MODDIR/system/bin/chrootctl"
STATE_FILE="$MODDIR/{state_path}"
[ -x "$HELPER" ] && [ -f "$HELPER" ] && [ ! -L "$HELPER" ] || {{ echo "module helper is missing or unsafe" >&2; exit 1; }}
[ -x "$CLI" ] && [ -f "$CLI" ] && [ ! -L "$CLI" ] || {{ echo "native chrootctl launcher is missing or unsafe" >&2; exit 1; }}
[ -f "$STATE_FILE" ] && [ ! -L "$STATE_FILE" ] || {{ echo "boot target state is missing or unsafe" >&2; exit 1; }}
STATE_ROOT=/data/adb/chrootctl
LOG_DIR="$STATE_ROOT/logs"
LOG_FILE="$LOG_DIR/module-boot.log"
LOCK_DIR="$STATE_ROOT/run/module-boot.lock"
[ ! -L "$STATE_ROOT" ] && [ ! -L "$LOG_DIR" ] && [ ! -L "$STATE_ROOT/run" ] && [ ! -L "$LOG_FILE" ] || {{ echo "unsafe module boot state path" >&2; exit 1; }}
mkdir -p "$LOG_DIR" "$STATE_ROOT/run"
[ -d "$STATE_ROOT" ] && [ ! -L "$STATE_ROOT" ] && [ -d "$LOG_DIR" ] && [ ! -L "$LOG_DIR" ] && [ -d "$STATE_ROOT/run" ] && [ ! -L "$STATE_ROOT/run" ] || {{ echo "unsafe module boot state directory" >&2; exit 1; }}
chmod 0700 "$STATE_ROOT" "$LOG_DIR" "$STATE_ROOT/run"

{lock_helpers}
if acquire_identity_lock "$LOCK_DIR" "$STATE_ROOT/run"; then
  :
else
  _lock_status=$?
  if [ "$_lock_status" -eq 2 ]; then
    printf '%s %s\n' "$(date +%s)" "boot orchestration already running" >>"$LOG_FILE"
    exit 0
  fi
  printf '%s %s\n' "$(date +%s)" "failed to acquire safe boot orchestration lock" >>"$LOG_FILE"
  exit 1
fi
trap 'release_identity_lock "$LOCK_DIR"' EXIT INT TERM

run_with_timeout() {{
  _seconds="$1"
  shift
  "$@" >>"$LOG_FILE" 2>&1 &
  _pid=$!
  _elapsed=0
  while kill -0 "$_pid" 2>/dev/null; do
    if [ "$_elapsed" -ge "$_seconds" ]; then
      printf '%s timeout: %s\n' "$(date +%s)" "$*" >>"$LOG_FILE"
      kill -TERM "$_pid" 2>/dev/null || true
      sleep 2
      kill -KILL "$_pid" 2>/dev/null || true
      wait "$_pid" 2>/dev/null || true
      return 124
    fi
    sleep 1
    _elapsed=$((_elapsed + 1))
  done
  wait "$_pid"
}}

printf '%s boot start\n' "$(date +%s)" >>"$LOG_FILE"
if ! run_with_timeout 90 "$HELPER" boot "$STATE_FILE"; then
  printf '%s startup target boot failed; boot orchestration failed\n' "$(date +%s)" >>"$LOG_FILE"
  exit 1
fi
if [ -f "$MODDIR/config/chrootctl/clipboard.enabled" ]; then
  run_with_timeout 20 "$CLI" clipboard daemon start || printf '%s clipboard startup failed\n' "$(date +%s)" >>"$LOG_FILE"
fi
printf '%s boot complete\n' "$(date +%s)" >>"$LOG_FILE"
exit 0
"""


def _helper_sh(config: MagiskModuleConfig) -> str:
    return f"""#!/system/bin/sh
set -eu
RAW_MODDIR=${{0%/*}}/..
EXPECTED="/data/adb/modules/{config.module_id}"
[ -d "$EXPECTED" ] && [ ! -L "$EXPECTED" ] || {{ echo "refusing missing or symlinked active module" >&2; exit 1; }}
MODDIR="$(cd "$RAW_MODDIR" && pwd -P)"
[ "$MODDIR" = "$EXPECTED" ] || {{ echo "refusing helper outside active module: $MODDIR" >&2; exit 1; }}
[ ! -e "$MODDIR/disable" ] && [ ! -e "$MODDIR/remove" ] || {{ echo "module is disabled or pending removal" >&2; exit 1; }}
CLI="$MODDIR/system/bin/chrootctl"
STATE_FILE=${{2:-}}
COMMAND=${{1:-}}
[ -x "$CLI" ] && [ -f "$CLI" ] && [ ! -L "$CLI" ] || {{ echo "missing or unsafe native chrootctl launcher" >&2; exit 1; }}

case "$COMMAND" in
  boot)
    [ -f "$STATE_FILE" ] && [ ! -L "$STATE_FILE" ] || {{ echo "missing or unsafe boot target state" >&2; exit 1; }}
    exec "$CLI" __module-boot "$STATE_FILE"
    ;;
  status|doctor|logs)
    shift
    exec "$CLI" "$COMMAND" "$@"
    ;;
  *)
    echo "unsupported helper command: $COMMAND" >&2
    exit 2
    ;;
esac
"""


def _module_dir_resolver_sh(module_id: str = DEFAULT_MODULE_ID) -> str:
    return f"""resolve_moddir() {{
  _active="/data/adb/modules/{module_id}"
  if [ -d "$_active" ] && [ ! -L "$_active" ] && [ -f "$_active/module.prop" ] && [ ! -L "$_active/module.prop" ] \\
    && grep -q '^id={module_id}$' "$_active/module.prop" 2>/dev/null \\
    && [ ! -e "$_active/disable" ] && [ ! -e "$_active/remove" ]; then
    _resolved="$(cd "$_active" 2>/dev/null && pwd -P)" || return 1
    [ "$_resolved" = "$_active" ] || return 1
    printf '%s\\n' "$_active"
    return 0
  fi
  for _pending in "/data/adb/modules_update/{module_id}" "/data/adb/ksu/modules_update/{module_id}"; do
    if [ -e "$_pending" ]; then
      echo "pending chrootctl module update exists at $_pending; reboot activation is required" >&2
    fi
  done
  return 1
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

if [ ! -x "$TARGET" ] || [ -L "$TARGET" ]; then
  echo "missing or unsafe module executable: $TARGET" >&2
  exit 1
fi

exec "$TARGET" "$@"
"""


def _native_entrypoint() -> str:
    resolver = _module_dir_resolver_sh()
    return f"""#!/system/bin/sh
set -eu
{resolver}
MODDIR="$(resolve_moddir)" || {{ echo "no active chrootctl module" >&2; exit 1; }}
case "$(uname -m 2>/dev/null || true)" in
  aarch64|arm64) RUNTIME_ABI="arm64-v8a" ;;
  *) echo "unsupported Android host architecture for chrootctl native runtime" >&2; exit 1 ;;
esac
RUNTIME_ROOT="$MODDIR/runtime/$RUNTIME_ABI"
RUNTIME_DIST="$RUNTIME_ROOT/chrootctl.dist"
RUNTIME_MANIFEST="$RUNTIME_ROOT/runtime-manifest.json"
RUNTIME_BIN="$RUNTIME_DIST/chrootctl-native-entry"
[ -d "$RUNTIME_ROOT" ] && [ ! -L "$RUNTIME_ROOT" ] && [ -d "$RUNTIME_DIST" ] && [ ! -L "$RUNTIME_DIST" ] || {{ echo "bundled native runtime directory is missing or unsafe" >&2; exit 1; }}
[ -f "$RUNTIME_MANIFEST" ] && [ ! -L "$RUNTIME_MANIFEST" ] || {{ echo "bundled native runtime manifest is missing or unsafe" >&2; exit 1; }}
[ -x "$RUNTIME_BIN" ] && [ -f "$RUNTIME_BIN" ] && [ ! -L "$RUNTIME_BIN" ] || {{ echo "bundled native chrootctl executable is missing or unsafe" >&2; exit 1; }}
_resolved_dist="$(cd "$RUNTIME_DIST" && pwd -P)" || exit 1
[ "$_resolved_dist" = "$RUNTIME_DIST" ] || {{ echo "bundled native runtime path is not canonical" >&2; exit 1; }}
export CHROOTCTL_MODULE_DIR="$MODDIR"
export LD_LIBRARY_PATH="$RUNTIME_DIST${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
exec "$RUNTIME_BIN" "$@"
"""


def _boot_targets_json(startup_targets: tuple[str, ...]) -> str:
    payload = {
        "startup_targets": list(startup_targets),
    }
    return json.dumps(payload, indent=2) + "\n"


def _parse_module_prop(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        if "=" not in raw:
            raise ValueError(f"invalid module.prop line: {raw!r}")
        key, value = raw.split("=", 1)
        if not key or key in values or any(ch in value for ch in "\r\n"):
            raise ValueError(f"invalid module.prop field: {key!r}")
        values[key] = value
    required = {"id", "name", "version", "versionCode", "author", "description"}
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError(f"module.prop missing fields: {', '.join(missing)}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]+", values["id"]):
        raise ValueError("module.prop id has invalid syntax")
    if values["id"] != DEFAULT_MODULE_ID:
        raise ValueError(f"unexpected module id: {values['id']}")
    try:
        version_code = int(values["versionCode"])
    except ValueError as exc:
        raise ValueError("module.prop versionCode must be an integer") from exc
    if version_code != DEFAULT_MODULE_VERSION_CODE or values["version"] != DEFAULT_MODULE_VERSION:
        raise ValueError("module.prop version identity does not match build constants")
    return values


def _validate_compatibility_manifest(path: Path, prop: dict[str, str]) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("compatibility manifest must be an object")
    expected = _compatibility_manifest_payload(MagiskModuleConfig())
    if payload != expected:
        raise ValueError("compatibility manifest does not match the exact module/Python/Android release identity")
    if prop.get("id") != DEFAULT_MODULE_ID or prop.get("version") != DEFAULT_MODULE_VERSION or int(prop.get("versionCode", "-1")) != DEFAULT_MODULE_VERSION_CODE:
        raise ValueError("module.prop identity does not match compatibility manifest build constants")
    return payload


def _validate_module_relative(relative: Path, *, directory: bool = False) -> None:
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"invalid module path: {relative}")
    text = relative.as_posix()
    if relative.parts[0] not in ALLOWED_MODULE_TOP_LEVEL:
        raise ValueError(f"module path is outside allow-list: {relative}")
    if _forbidden_module_relative_path(relative):
        raise ValueError(f"forbidden module artifact: {relative}")
    if directory:
        if text in _ALLOWED_MODULE_DIRS:
            return
        raise ValueError(f"module directory is outside nested allow-list: {relative}")
    if text in REQUIRED_MODULE_PATHS:
        return
    raise ValueError(f"module file is outside nested allow-list: {relative}")

def validate_magisk_module(output_dir: Path) -> tuple[Path, ...]:
    output_dir = output_dir.expanduser().resolve()
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise NotADirectoryError(f"module output must be a real directory: {output_dir}")
    required_paths = tuple(Path(path) for path in sorted(REQUIRED_MODULE_PATHS))
    missing = tuple(path for path in required_paths if not (output_dir / path).exists())
    if missing:
        raise FileNotFoundError("invalid module output; missing: " + ", ".join(map(str, missing)))
    total = 0
    for path in sorted(output_dir.rglob("*")):
        relative = path.relative_to(output_dir)
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in module payload: {relative}")
        _validate_module_relative(relative, directory=path.is_dir())
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"non-regular module payload entry: {relative}")
        size = path.stat().st_size
        if size > MODULE_MAX_FILE_BYTES:
            raise ValueError(f"module file exceeds size limit: {relative}")
        total += size
        if total > MODULE_MAX_TOTAL_BYTES:
            raise ValueError("module payload exceeds total size limit")
    prop = _parse_module_prop(output_dir / "module.prop")
    _validate_compatibility_manifest(output_dir / "config/chrootctl/compatibility-manifest.json", prop)
    validate_native_runtime_artifact(
        output_dir / NATIVE_RUNTIME_MODULE_ROOT,
        expected_abi=DEFAULT_NATIVE_RUNTIME_ABI,
        package_version=PYTHON_PACKAGE_VERSION,
        bridge_protocol_version=BRIDGE_PROTOCOL_VERSION,
    )
    for relative in REQUIRED_EXECUTABLE_PATHS:
        path = output_dir / relative
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o111 == 0:
            raise PermissionError(f"required module executable lacks execute permission: {relative}")
    return tuple(output_dir / path for path in required_paths)


def _validate_native_runtime_zip(archive: zipfile.ZipFile) -> None:
    prefix = NATIVE_RUNTIME_MODULE_ROOT.as_posix() + "/"
    manifest_name = NATIVE_RUNTIME_MANIFEST_PATH.as_posix()
    payload = json.loads(archive.read(manifest_name).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("native runtime manifest must be a JSON object")
    expected = {
        "schemaVersion": 1,
        "runtimeKind": "nuitka-onefile",
        "platform": "android",
        "abi": DEFAULT_NATIVE_RUNTIME_ABI,
        "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
        "pythonPackageVersion": PYTHON_PACKAGE_VERSION,
        "bridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"native runtime zip manifest {key} mismatch")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("native runtime zip manifest file inventory is missing")
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValueError("native runtime zip manifest contains invalid file metadata")
        relative = Path(str(raw.get("path") or ""))
        if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError(f"unsafe native runtime zip inventory path: {relative}")
        rel_text = relative.as_posix()
        if rel_text in seen or rel_text == "runtime-manifest.json":
            raise ValueError(f"invalid native runtime zip inventory entry: {rel_text}")
        seen.add(rel_text)
        full_name = prefix + rel_text
        try:
            info = archive.getinfo(full_name)
        except KeyError as exc:
            raise FileNotFoundError(f"native runtime zip inventory entry is missing: {full_name}") from exc
        data = archive.read(info)
        if info.file_size != raw.get("size"):
            raise ValueError(f"native runtime zip size mismatch: {full_name}")
        if hashlib.sha256(data).hexdigest() != raw.get("sha256"):
            raise ValueError(f"native runtime zip checksum mismatch: {full_name}")
        mode = (info.external_attr >> 16) & 0o777
        if bool(mode & 0o111) != bool(raw.get("executable")):
            raise ValueError(f"native runtime zip executable mode mismatch: {full_name}")
    actual = {
        info.filename[len(prefix):]
        for info in archive.infolist()
        if info.filename.startswith(prefix) and not info.is_dir() and info.filename != manifest_name
    }
    if actual != seen:
        raise ValueError(f"native runtime zip file inventory mismatch; missing={sorted(seen - actual)}, extra={sorted(actual - seen)}")
    entrypoint_name = NATIVE_RUNTIME_ENTRYPOINT_PATH.as_posix()
    entrypoint = archive.read(entrypoint_name)
    if entrypoint[:4] != b"\x7fELF":
        raise ValueError("native runtime zip entrypoint is not an ELF executable")


def _validate_no_external_python_bootstrap_residue(names: set[str], text_payloads: dict[str, str]) -> None:
    forbidden_paths = {
        "bin/chrootctl-python-bootstrap",
        "system/bin/chrootctl-python-bootstrap",
        "config/chrootctl/python.env",
        "config/chrootctl/dependencies.ready.json",
        "config/chrootctl/dependency-mode.env",
        "payload/requirements.txt",
        "payload/pyproject.toml",
    }
    present = sorted(name for name in names if name in forbidden_paths or name.startswith("payload/"))
    if present:
        raise ValueError("external Python bootstrap residue in module zip: " + ", ".join(present[:20]))

    forbidden_tokens = (
        "chrootctl-python-bootstrap",
        "python.env",
        "dependencies.ready.json",
        "dependency-mode.env",
        "DEPENDENCY_MODE=static-python-env",
        "dependencyContractSha256",
        "command -v python3",
        "pip install",
        "/data/adb/py2droid",
        "/data/data/com.termux/files/usr/bin/python3",
        "PYTHONPATH=\"$MODDIR/payload/src\"",
    )
    findings: list[str] = []
    for name, payload in sorted(text_payloads.items()):
        for token in forbidden_tokens:
            if token in payload:
                findings.append(f"{name}:{token}")
                break
    if findings:
        raise ValueError("external Python bootstrap residue in module scripts: " + ", ".join(findings[:20]))


def validate_magisk_zip(zip_path: Path) -> tuple[str, ...]:
    zip_path = zip_path.expanduser().resolve()
    required = set(REQUIRED_MODULE_PATHS)
    total = 0
    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("module zip contains duplicate entry names")
        normalized: set[str] = set()
        text_payloads: dict[str, str] = {}
        for info in infos:
            raw = info.filename
            if raw.startswith(("/", "\\")) or "\\" in raw:
                raise ValueError(f"invalid zip entry path: {raw}")
            if "\x00" in raw:
                raise ValueError("module zip entry contains NUL")
            relative = Path(raw.rstrip("/"))
            if not relative.parts:
                continue
            canonical = relative.as_posix() + ("/" if info.is_dir() else "")
            if raw != canonical:
                raise ValueError(f"module zip entry path is not canonical: {raw}")
            _validate_module_relative(relative, directory=info.is_dir())
            if relative.as_posix() in normalized:
                raise ValueError(f"module zip contains normalized duplicate path: {raw}")
            normalized.add(relative.as_posix())
            if info.flag_bits & 0x1:
                raise ValueError(f"encrypted module zip entries are not allowed: {raw}")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError(f"unsupported module zip compression method: {raw}")
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                raise ValueError(f"module zip contains symlink: {raw}")
            if not info.is_dir() and file_type not in {0, stat.S_IFREG}:
                raise ValueError(f"module zip contains non-regular entry: {raw}")
            if info.file_size > MODULE_MAX_FILE_BYTES:
                raise ValueError(f"module zip entry exceeds size limit: {raw}")
            total += info.file_size
            if total > MODULE_MAX_TOTAL_BYTES:
                raise ValueError("module zip exceeds total uncompressed size limit")
            if not info.is_dir() and raw.endswith((".sh", ".json", ".prop")) and info.file_size <= 1024 * 1024:
                try:
                    text_payloads[raw] = archive.read(info).decode("utf-8")
                except UnicodeDecodeError:
                    pass
        _validate_no_external_python_bootstrap_residue(normalized, text_payloads)
        # Only decompress for CRC verification after central-directory metadata has
        # passed the per-file and aggregate uncompressed-size bounds.
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise ValueError(f"module zip CRC validation failed: {bad_crc}")
        missing = sorted(required - normalized)
        if missing:
            raise FileNotFoundError("module zip missing required entries: " + ", ".join(missing))
        for relative in REQUIRED_EXECUTABLE_PATHS:
            try:
                info = archive.getinfo(relative)
            except KeyError as exc:
                raise FileNotFoundError(f"module zip missing executable: {relative}") from exc
            mode = (info.external_attr >> 16) & 0o777
            if mode & 0o111 == 0:
                raise PermissionError(f"module zip executable mode missing: {relative}")
        prop_text = archive.read("module.prop").decode("utf-8")
        with tempfile.TemporaryDirectory(prefix="chrootctl-module-zip-check-") as tmp:
            tmpdir = Path(tmp)
            (tmpdir / "module.prop").write_text(prop_text, encoding="utf-8")
            prop = _parse_module_prop(tmpdir / "module.prop")
            compat = json.loads(archive.read("config/chrootctl/compatibility-manifest.json").decode("utf-8"))
            compat_path = tmpdir / "compat.json"
            compat_path.write_text(json.dumps(compat), encoding="utf-8")
            _validate_compatibility_manifest(compat_path, prop)
        _validate_native_runtime_zip(archive)
    return tuple(names)


def zip_magisk_module(output_dir: Path, zip_path: Path) -> Path:
    output_dir = output_dir.expanduser().resolve()
    zip_path = zip_path.expanduser().resolve()
    validate_magisk_module(output_dir)
    try:
        zip_path.relative_to(output_dir)
    except ValueError:
        pass
    else:
        raise ValueError("module zip destination must not be inside module output directory")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists() and (zip_path.is_dir() or zip_path.is_symlink()):
        raise ValueError(f"refusing unsafe module zip destination: {zip_path}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{zip_path.name}.", suffix=".tmp", dir=str(zip_path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(output_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(output_dir).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                runtime_file = relative.startswith(NATIVE_RUNTIME_MODULE_ROOT.as_posix() + "/")
                mode = 0o755 if relative in REQUIRED_EXECUTABLE_PATHS or (runtime_file and path.stat().st_mode & 0o111) else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as source:
                    archive.writestr(info, source.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        validate_magisk_zip(tmp)
        os.replace(tmp, zip_path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    validate_magisk_zip(zip_path)
    return zip_path
