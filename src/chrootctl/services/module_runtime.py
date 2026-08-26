from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..magisk import (
    ANDROID_APP_VERSION_CODE,
    ANDROID_APP_VERSION_NAME,
    BRIDGE_PROTOCOL_VERSION,
    DEFAULT_MODULE_ID,
    DEFAULT_MODULE_VERSION,
    DEFAULT_MODULE_VERSION_CODE,
    PYTHON_PACKAGE_VERSION,
)
from ..native_runtime import (
    DEFAULT_NATIVE_RUNTIME_ABI,
    DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
    NATIVE_RUNTIME_KIND,
    validate_native_runtime_artifact,
)

ACTIVE_MODULE_ROOT = Path("/data/adb/modules")
PENDING_MODULE_ROOTS = (
    Path("/data/adb/modules_update"),
    Path("/data/adb/ksu/modules_update"),
)
_NATIVE_RUNTIME_RELATIVE = Path("runtime") / DEFAULT_NATIVE_RUNTIME_ABI
_NATIVE_RUNTIME_MANIFEST_RELATIVE = _NATIVE_RUNTIME_RELATIVE / "runtime-manifest.json"
_NATIVE_RUNTIME_ENTRYPOINT_RELATIVE = _NATIVE_RUNTIME_RELATIVE / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT


@dataclass(frozen=True, slots=True)
class ModuleRuntimePaths:
    module_id: str = DEFAULT_MODULE_ID
    active_root: Path = ACTIVE_MODULE_ROOT
    pending_roots: tuple[Path, ...] = PENDING_MODULE_ROOTS

    @property
    def active_dir(self) -> Path:
        return self.active_root / self.module_id

    @property
    def pending_dirs(self) -> tuple[Path, ...]:
        return tuple(root / self.module_id for root in self.pending_roots)


class ModuleRuntimeStatusService:
    """Authoritative active/pending/readiness model for the root module.

    Runtime execution is restricted to the active module tree.  Pending update
    trees are diagnostics only.  A module is runtime-ready only when its sealed
    bundled native runtime validates against this release's package and bridge
    identities; external Python installations are deliberately irrelevant.
    """

    def __init__(self, paths: ModuleRuntimePaths | None = None) -> None:
        self.paths = paths or ModuleRuntimePaths()

    def status(self) -> dict[str, Any]:
        active = self._candidate(self.paths.active_dir, pending=False)
        pending = [self._candidate(path, pending=True) for path in self.paths.pending_dirs if path.exists()]
        active_usable = bool(active.get("active"))
        runtime = active.get("runtimeReadiness") if isinstance(active.get("runtimeReadiness"), dict) else {}
        warnings: list[str] = []
        if not active.get("exists"):
            warnings.append("No installed chrootctl Magisk/KernelSU module was detected in /data/adb/modules.")
        elif active.get("disabled"):
            warnings.append("The installed chrootctl module is disabled.")
        elif active.get("pendingRemoval"):
            warnings.append("The installed chrootctl module is marked for removal on reboot.")
        elif not active.get("layoutReady"):
            warnings.append("The installed chrootctl module is missing required bundled-native runtime files.")
        if pending:
            warnings.append("A pending module update exists and is intentionally excluded from runtime execution until reboot activation.")
        if active_usable and not runtime.get("ready", False):
            warnings.append("The active module bundled-native runtime seal is missing, stale, or invalid.")
        return {
            "moduleId": self.paths.module_id,
            "installed": bool(active.get("exists")),
            "active": active if active_usable else None,
            "installedState": active,
            "pendingUpdate": bool(pending),
            "pending": pending,
            "ready": active_usable and bool(runtime.get("ready", False)),
            "manager": self._detect_manager(),
            "warnings": warnings,
        }

    def active_executable(self) -> Path | None:
        candidate = self._candidate(self.paths.active_dir, pending=False)
        readiness = candidate.get("runtimeReadiness") if isinstance(candidate.get("runtimeReadiness"), dict) else {}
        if not candidate.get("active") or not readiness.get("ready"):
            return None
        executable = self.paths.active_dir / "system/bin/chrootctl"
        return executable if self._regular_file_in_module(executable, self.paths.active_dir) else None

    def _candidate(self, root: Path, *, pending: bool) -> dict[str, Any]:
        prop_path = root / "module.prop"
        root_safe = self._canonical_module_dir(root)
        prop_safe = root_safe and self._regular_file_in_module(prop_path, root)
        prop = self._read_key_values(prop_path) if prop_safe else {}
        module_id = prop.get("id", "")
        disabled = (root / "disable").exists()
        remove = (root / "remove").exists()
        required_files = (
            root / "system/bin/chrootctl",
            root / "bin/chrootctl-magisk-helper",
            root / "config/chrootctl/compatibility-manifest.json",
            root / _NATIVE_RUNTIME_MANIFEST_RELATIVE,
            root / _NATIVE_RUNTIME_ENTRYPOINT_RELATIVE,
        )
        layout_ready = bool(
            root_safe
            and prop_safe
            and module_id == self.paths.module_id
            and all(self._regular_file_in_module(path, root) for path in required_files)
        )
        active = bool(layout_ready and not pending and not disabled and not remove and self._contained_in_active_root(root))
        compatibility = self._compatibility(root, prop) if root.exists() else {"valid": False, "reason": "module_missing"}
        readiness = self._native_runtime_readiness(root, compatibility) if root.exists() else {"ready": False, "reason": "module_missing"}
        try:
            version_code = int(prop.get("versionCode", ""))
        except ValueError:
            version_code = None
        return {
            "path": str(root),
            "exists": root.exists(),
            "pending": pending,
            "active": active,
            "disabled": disabled,
            "pendingRemoval": remove,
            "hasModuleProp": bool(prop_safe),
            "layoutReady": layout_ready,
            "id": module_id,
            "name": prop.get("name", ""),
            "version": prop.get("version", ""),
            "versionCode": version_code,
            "compatibility": compatibility,
            "runtimeReadiness": readiness,
            # Compatibility alias for older bridge/UI clients.  Its payload now
            # describes the bundled native runtime, not external Python deps.
            "dependencyReadiness": readiness,
        }

    def _native_runtime_readiness(self, root: Path, compatibility: dict[str, Any]) -> dict[str, Any]:
        runtime_root = root / _NATIVE_RUNTIME_RELATIVE
        manifest_path = root / _NATIVE_RUNTIME_MANIFEST_RELATIVE
        entrypoint = root / _NATIVE_RUNTIME_ENTRYPOINT_RELATIVE
        base: dict[str, Any] = {
            "ready": False,
            "mode": "bundled-native",
            "runtimeKind": NATIVE_RUNTIME_KIND,
            "abi": DEFAULT_NATIVE_RUNTIME_ABI,
            "path": str(manifest_path),
            "executable": str(entrypoint),
            "pythonPackageVersion": PYTHON_PACKAGE_VERSION,
            "bridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        }
        if not compatibility.get("valid"):
            return {**base, "reason": "compatibility_manifest_invalid"}
        if not self._real_dir_in_module(runtime_root, root):
            return {**base, "reason": "native_runtime_directory_missing_or_unsafe"}
        if not self._regular_file_in_module(manifest_path, root):
            return {**base, "reason": "native_runtime_manifest_missing_or_unsafe"}
        if not self._regular_file_in_module(entrypoint, root) or entrypoint.stat().st_mode & 0o111 == 0:
            return {**base, "reason": "native_runtime_entrypoint_missing_or_unsafe"}
        try:
            manifest = validate_native_runtime_artifact(
                runtime_root,
                expected_abi=DEFAULT_NATIVE_RUNTIME_ABI,
                package_version=PYTHON_PACKAGE_VERSION,
                bridge_protocol_version=BRIDGE_PROTOCOL_VERSION,
            )
        except (OSError, ValueError, TypeError) as exc:
            return {**base, "reason": "native_runtime_integrity_invalid", "detail": str(exc)}
        return {
            **base,
            "ready": True,
            "reason": "ok",
            "compiler": manifest.get("compiler"),
            "files": len(manifest.get("files", [])) if isinstance(manifest.get("files"), list) else 0,
        }

    def _compatibility(self, root: Path, prop: dict[str, str]) -> dict[str, Any]:
        path = root / "config/chrootctl/compatibility-manifest.json"
        if not self._regular_file_in_module(path, root):
            return {"valid": False, "reason": "missing_or_unsafe", "path": str(path)}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            return {"valid": False, "reason": "invalid", "detail": type(exc).__name__, "path": str(path)}
        module = payload.get("module") if isinstance(payload, dict) else None
        python = payload.get("pythonPackage") if isinstance(payload, dict) else None
        android = payload.get("androidApp") if isinstance(payload, dict) else None
        try:
            prop_version_code = int(prop.get("versionCode", ""))
        except ValueError:
            prop_version_code = -1
        valid = bool(
            isinstance(payload, dict)
            and payload.get("schemaVersion") == 2
            and payload.get("project") == "chrootctl"
            and payload.get("bridgeProtocolVersion") == BRIDGE_PROTOCOL_VERSION
            and isinstance(module, dict)
            and module.get("id") == self.paths.module_id
            and module.get("version") == DEFAULT_MODULE_VERSION
            and module.get("version") == prop.get("version")
            and module.get("versionCode") == DEFAULT_MODULE_VERSION_CODE
            and module.get("versionCode") == prop_version_code
            and module.get("minimumSupportedBridgeProtocolVersion") == BRIDGE_PROTOCOL_VERSION
            and isinstance(python, dict)
            and python.get("name") == "chrootctl"
            and python.get("version") == PYTHON_PACKAGE_VERSION
            and isinstance(android, dict)
            and android.get("applicationId") == "com.mikeyphw.chrootctl"
            and android.get("versionName") == ANDROID_APP_VERSION_NAME
            and android.get("versionCode") == ANDROID_APP_VERSION_CODE
            and android.get("minimumSupportedModuleVersionCode") == DEFAULT_MODULE_VERSION_CODE
        )
        return {"valid": valid, "reason": "ok" if valid else "identity_mismatch", "path": str(path), "manifest": payload if valid else None}

    @staticmethod
    def _canonical_module_dir(root: Path) -> bool:
        try:
            return root.is_dir() and not root.is_symlink() and root.resolve(strict=True) == root.absolute()
        except OSError:
            return False

    @staticmethod
    def _regular_file_in_module(path: Path, root: Path) -> bool:
        try:
            if path.is_symlink() or not path.is_file():
                return False
            resolved_root = root.resolve(strict=True)
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
            return resolved == path.absolute()
        except (OSError, ValueError):
            return False

    @staticmethod
    def _real_dir_in_module(path: Path, root: Path) -> bool:
        try:
            if path.is_symlink() or not path.is_dir():
                return False
            resolved_root = root.resolve(strict=True)
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
            return resolved == path.absolute()
        except (OSError, ValueError):
            return False

    def _contained_in_active_root(self, root: Path) -> bool:
        try:
            return root.resolve(strict=False).parent == self.paths.active_root.resolve(strict=False)
        except OSError:
            return False

    @staticmethod
    def _read_key_values(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return values
        for line in lines:
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    @staticmethod
    def _detect_manager() -> str:
        if Path("/data/adb/ksu").exists() or "KernelSU" in platform.uname().release:
            return "KernelSU"
        if Path("/data/adb/magisk").exists():
            return "Magisk"
        return "unknown"
