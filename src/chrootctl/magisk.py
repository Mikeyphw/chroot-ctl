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
BACKEND_IMPLEMENTATION = "go"
BACKEND_VERSION = "0.11.0"
PYTHON_PACKAGE_VERSION = BACKEND_VERSION  # legacy source/test alias until GO17
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
        "schemaVersion": 3,
        "project": "chrootctl",
        "bridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        "backend": {
            "implementation": BACKEND_IMPLEMENTATION,
            "version": BACKEND_VERSION,
        },
        "nativeRuntime": {
            "schemaVersion": 2,
            "kind": "go-native",
            "platform": "android",
            "abi": DEFAULT_NATIVE_RUNTIME_ABI,
            "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
        },
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
# KernelSU/Magisk source this file inside the installer shell.
# Avoid shell nounset and runtime validation here; either can abort install.

SKIPMOUNT=false
PROPFILE=false
POSTFSDATA=true
LATESTARTSERVICE=true
REPLACE=""

ui_print "chrootctl ships a bundled native runtime; no external Python environment is installed or required." 2>/dev/null || \
  echo "chrootctl ships a bundled native runtime; no external Python environment is installed or required."

return 0 2>/dev/null || exit 0
"""


def _post_fs_data_sh() -> str:
    return """#!/system/bin/sh
# chrootctl does not need post-fs-data bootstrap work.
exit 0
"""


def _service_sh(config: MagiskModuleConfig) -> str:
    module_id = config.module_id
    helper_path = config.helper_path()
    return f"""#!/system/bin/sh
MODDIR="${{0%/*}}"
case "$MODDIR" in
  */system/bin) MODDIR="${{MODDIR%/system/bin}}" ;;
esac
ACTIVE_MODULE="/data/adb/modules/{module_id}"
UPDATE_MODULE="/data/adb/modules_update/{module_id}" # diagnostics only

if [ -n "${{CHROOTCTL_MODULE_DIR:-}}" ]; then
  MODDIR="$CHROOTCTL_MODULE_DIR"
elif [ -d "$ACTIVE_MODULE" ]; then
  MODDIR="$ACTIVE_MODULE"
fi

if [ "$MODDIR" != "$ACTIVE_MODULE" ]; then
  echo "refusing module service outside active module: $MODDIR" >&2
  exit 0
fi

HELPER="$MODDIR/{helper_path}"
[ -x "$HELPER" ] || exit 0
"$HELPER" __module-service clipboard.enabled || true
"""


def _helper_sh(config: MagiskModuleConfig) -> str:
    return """#!/system/bin/sh
set -eu
CMD="${1:-}"
shift 2>/dev/null || true
case "$CMD" in
  __module-boot)
    exit 0
    ;;
  __module-service)
    # Keep service hooks narrow; runtime operations are handled by the native CLI.
    exit 0
    ;;
  *)
    echo "unsupported chrootctl module helper command: $CMD" >&2
    exit 2
    ;;
esac
"""


def _native_entrypoint() -> str:
    return """#!/system/bin/sh
set -eu

MODULE_ID="chrootctl-magisk"
RUNTIME_ABI="arm64-v8a"
ACTIVE_MODULE="/data/adb/modules/chrootctl-magisk"
UPDATE_MODULE="/data/adb/modules_update/chrootctl-magisk" # diagnostics only

MODDIR="${CHROOTCTL_MODULE_DIR:-}"
if [ -z "$MODDIR" ]; then
  MODDIR="$ACTIVE_MODULE"
fi

RUNTIME_ROOT="$MODDIR/runtime/$RUNTIME_ABI"
RUNTIME_MANIFEST="$RUNTIME_ROOT/runtime-manifest.json"
RUNTIME_BIN="$RUNTIME_ROOT/chrootctl"

[ -d "$RUNTIME_ROOT" ] && [ ! -L "$RUNTIME_ROOT" ] || { echo "bundled native runtime directory is missing or unsafe" >&2; exit 127; }
[ -f "$RUNTIME_MANIFEST" ] && [ ! -L "$RUNTIME_MANIFEST" ] || { echo "bundled native runtime manifest is missing or unsafe" >&2; exit 127; }
[ -f "$RUNTIME_BIN" ] && [ -x "$RUNTIME_BIN" ] && [ ! -L "$RUNTIME_BIN" ] || { echo "bundled native chrootctl executable is missing or unsafe" >&2; exit 127; }

mkdir -p /data/adb/chrootctl 2>/dev/null || true
chmod 0700 /data/adb/chrootctl 2>/dev/null || true

export CHROOTCTL_MODULE_DIR="$MODDIR"
exec "$RUNTIME_BIN" "$@"
"""


def _system_bin_proxy(target: str) -> str:
    if target.startswith("/") or ".." in Path(target).parts:
        raise ValueError(f"unsafe system/bin proxy target: {target}")
    return f"""#!/system/bin/sh
MODDIR="${{CHROOTCTL_MODULE_DIR:-/data/adb/modules/chrootctl-magisk}}"
exec "$MODDIR/{target}" "$@"
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
        raise ValueError("compatibility manifest does not match the exact module/backend/Android release identity")
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
    runtime_prefix = NATIVE_RUNTIME_MODULE_ROOT.as_posix() + "/"
    if text.startswith(runtime_prefix):
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
        "schemaVersion": 2,
        "runtimeKind": "go-native",
        "platform": "android",
        "abi": DEFAULT_NATIVE_RUNTIME_ABI,
        "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
        "backendVersion": PYTHON_PACKAGE_VERSION,
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
