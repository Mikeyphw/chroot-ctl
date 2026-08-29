from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .magisk import (
    ANDROID_APP_VERSION_CODE,
    BACKEND_IMPLEMENTATION,
    BACKEND_VERSION,
    ANDROID_APP_VERSION_NAME,
    BRIDGE_PROTOCOL_VERSION,
    DEFAULT_MODULE_ID,
    DEFAULT_MODULE_VERSION,
    DEFAULT_MODULE_VERSION_CODE,
    PYTHON_PACKAGE_VERSION,
)
from .native_runtime import (
    DEFAULT_NATIVE_RUNTIME_ABI,
    DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
    LEGACY_NATIVE_RUNTIME_KIND,
    LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION,
    NATIVE_RUNTIME_KIND,
    NATIVE_RUNTIME_PLATFORM,
    NATIVE_RUNTIME_SCHEMA_VERSION,
)

ANDROID_APPLICATION_ID = "com.mikeyphw.chrootctl"
COMPATIBILITY_SCHEMA_VERSION = 3
LEGACY_COMPATIBILITY_SCHEMA_VERSION = 2
RUNTIME_RESOLVER_PATH = Path("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
COMPATIBILITY_MANIFEST_PATH = Path("docs/release/compatibility-manifest.json")

_KOTLIN_CONST_RE = re.compile(
    r"private\s+const\s+val\s+(?P<name>[A-Z0-9_]+)\s*=\s*(?P<value>\"[^\"]*\"|-?\d+)"
)


@dataclass(frozen=True, slots=True)
class ParityCheckResult:
    ok: bool
    checked: tuple[str, ...]
    mismatches: tuple[str, ...]

    def require_ok(self) -> None:
        if not self.ok:
            raise ValueError("release parity check failed: " + "; ".join(self.mismatches))


def _parse_kotlin_constants(path: Path) -> dict[str, str | int]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"missing safe Android runtime resolver: {path}")
    values: dict[str, str | int] = {}
    for match in _KOTLIN_CONST_RE.finditer(path.read_text(encoding="utf-8")):
        raw = match.group("value")
        values[match.group("name")] = raw[1:-1] if raw.startswith('"') else int(raw)
    return values


def expected_runtime_resolver_constants() -> dict[str, str | int]:
    return {
        "BRIDGE_PROTOCOL_VERSION": BRIDGE_PROTOCOL_VERSION,
        "NATIVE_RUNTIME_SCHEMA_VERSION": NATIVE_RUNTIME_SCHEMA_VERSION,
        "NATIVE_RUNTIME_KIND": NATIVE_RUNTIME_KIND,
        "LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION": LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION,
        "LEGACY_NATIVE_RUNTIME_KIND": LEGACY_NATIVE_RUNTIME_KIND,
        "NATIVE_RUNTIME_PLATFORM": NATIVE_RUNTIME_PLATFORM,
        "NATIVE_RUNTIME_ABI": DEFAULT_NATIVE_RUNTIME_ABI,
        "NATIVE_RUNTIME_ROOT": f"runtime/{DEFAULT_NATIVE_RUNTIME_ABI}",
        "NATIVE_RUNTIME_ENTRYPOINT": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
        "MODULE_ID": DEFAULT_MODULE_ID,
        "EXPECTED_MODULE_VERSION": DEFAULT_MODULE_VERSION,
        "MIN_SUPPORTED_MODULE_VERSION_CODE": DEFAULT_MODULE_VERSION_CODE,
        "EXPECTED_BACKEND_IMPLEMENTATION": BACKEND_IMPLEMENTATION,
        "EXPECTED_BACKEND_VERSION": BACKEND_VERSION,
        "EXPECTED_PYTHON_PACKAGE_VERSION": PYTHON_PACKAGE_VERSION,
        "COMPATIBILITY_SCHEMA_VERSION": COMPATIBILITY_SCHEMA_VERSION,
        "LEGACY_COMPATIBILITY_SCHEMA_VERSION": LEGACY_COMPATIBILITY_SCHEMA_VERSION,
        "EXPECTED_ANDROID_VERSION_NAME": ANDROID_APP_VERSION_NAME,
        "EXPECTED_ANDROID_VERSION_CODE": ANDROID_APP_VERSION_CODE,
    }


def expected_compatibility_manifest() -> dict[str, object]:
    return {
        "schemaVersion": COMPATIBILITY_SCHEMA_VERSION,
        "project": "chrootctl",
        "bridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        "backend": {"implementation": BACKEND_IMPLEMENTATION, "version": BACKEND_VERSION},
        "nativeRuntime": {
            "schemaVersion": NATIVE_RUNTIME_SCHEMA_VERSION,
            "kind": NATIVE_RUNTIME_KIND,
            "platform": NATIVE_RUNTIME_PLATFORM,
            "abi": DEFAULT_NATIVE_RUNTIME_ABI,
            "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
        },
        "androidApp": {
            "applicationId": ANDROID_APPLICATION_ID,
            "versionName": ANDROID_APP_VERSION_NAME,
            "versionCode": ANDROID_APP_VERSION_CODE,
            "minimumSupportedModuleVersionCode": DEFAULT_MODULE_VERSION_CODE,
        },
        "module": {
            "id": DEFAULT_MODULE_ID,
            "version": DEFAULT_MODULE_VERSION,
            "versionCode": DEFAULT_MODULE_VERSION_CODE,
            "minimumSupportedBridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        },
    }


def _manifest_mismatches(path: Path, expected: Mapping[str, object]) -> list[str]:
    if not path.is_file() or path.is_symlink():
        return [f"{path}: missing or unsafe"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload != expected:
        return [f"{path}: compatibility manifest does not match build constants"]
    return []


def check_release_parity(repo_root: Path) -> ParityCheckResult:
    repo_root = repo_root.expanduser().resolve()
    checked: list[str] = []
    mismatches: list[str] = []

    runtime_resolver = repo_root / RUNTIME_RESOLVER_PATH
    actual = _parse_kotlin_constants(runtime_resolver)
    expected = expected_runtime_resolver_constants()
    for key, expected_value in sorted(expected.items()):
        checked.append(f"RuntimeResolver.kt:{key}")
        actual_value = actual.get(key)
        if actual_value != expected_value:
            mismatches.append(f"RuntimeResolver.kt:{key}: expected {expected_value!r}, got {actual_value!r}")

    manifest_path = repo_root / COMPATIBILITY_MANIFEST_PATH
    checked.append(str(COMPATIBILITY_MANIFEST_PATH))
    mismatches.extend(_manifest_mismatches(manifest_path, expected_compatibility_manifest()))

    return ParityCheckResult(ok=not mismatches, checked=tuple(checked), mismatches=tuple(mismatches))
