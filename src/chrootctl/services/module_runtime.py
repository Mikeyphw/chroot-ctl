from __future__ import annotations

import hashlib
import json
import os
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
    DEFAULT_PYTHON_DEPENDENCIES,
    PYTHON_PACKAGE_VERSION,
)
_REQUIRED_DEPENDENCY_MINIMUMS = {
    "rich": (13, 7, 0),
    "PyYAML": (6, 0),
    "pydantic": (2, 7, 0),
    "pydantic-core": (2, 0),
}
ACTIVE_MODULE_ROOT = Path("/data/adb/modules")
PENDING_MODULE_ROOTS = (
    Path("/data/adb/modules_update"),
    Path("/data/adb/ksu/modules_update"),
)


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

    Runtime execution is intentionally restricted to /data/adb/modules. Pending
    update trees are diagnostics only and must never be selected for execution.
    """

    def __init__(self, paths: ModuleRuntimePaths | None = None) -> None:
        self.paths = paths or ModuleRuntimePaths()

    def status(self) -> dict[str, Any]:
        active = self._candidate(self.paths.active_dir, pending=False)
        pending = [self._candidate(path, pending=True) for path in self.paths.pending_dirs if path.exists()]
        active_usable = bool(active.get("active"))
        warnings: list[str] = []
        if not active.get("exists"):
            warnings.append("No installed chrootctl Magisk/KernelSU module was detected in /data/adb/modules.")
        elif active.get("disabled"):
            warnings.append("The installed chrootctl module is disabled.")
        elif active.get("pendingRemoval"):
            warnings.append("The installed chrootctl module is marked for removal on reboot.")
        elif not active.get("layoutReady"):
            warnings.append("The installed chrootctl module is missing required runtime payload files.")
        if pending:
            warnings.append("A pending module update exists and is intentionally excluded from runtime execution until reboot activation.")
        dependency = active.get("dependencyReadiness") if isinstance(active.get("dependencyReadiness"), dict) else {}
        if active_usable and not dependency.get("ready", False):
            warnings.append("The active module dependency readiness record is missing, stale, or not ready.")
        return {
            "moduleId": self.paths.module_id,
            "installed": bool(active.get("exists")),
            "active": active if active_usable else None,
            "installedState": active,
            "pendingUpdate": bool(pending),
            "pending": pending,
            "ready": active_usable and bool(dependency.get("ready", False)),
            "manager": self._detect_manager(),
            "warnings": warnings,
        }

    def active_executable(self) -> Path | None:
        candidate = self._candidate(self.paths.active_dir, pending=False)
        if not candidate.get("active"):
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
            root / "bin/chrootctl-python-bootstrap",
            root / "config/chrootctl/compatibility-manifest.json",
            root / "config/chrootctl/dependency-mode.env",
            root / "payload/requirements.txt",
        )
        required_dirs = (root / "payload/src/chrootctl",)
        layout_ready = bool(
            root_safe
            and prop_safe
            and module_id == self.paths.module_id
            and all(self._regular_file_in_module(path, root) for path in required_files)
            and all(self._real_dir_in_module(path, root) for path in required_dirs)
            and self._dependency_contract_valid(root)
        )
        active = bool(layout_ready and not pending and not disabled and not remove and self._contained_in_active_root(root))
        compatibility = self._compatibility(root, prop) if root.exists() else {"valid": False, "reason": "module_missing"}
        readiness = self._dependency_readiness(root, compatibility) if root.exists() else {"ready": False, "reason": "module_missing"}
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
            "dependencyReadiness": readiness,
        }

    def _dependency_contract_valid(self, root: Path) -> bool:
        mode_path = root / "config/chrootctl/dependency-mode.env"
        requirements_path = root / "payload/requirements.txt"
        if not self._regular_file_in_module(mode_path, root) or not self._regular_file_in_module(requirements_path, root):
            return False
        try:
            mode_text = mode_path.read_text(encoding="utf-8")
            requirements_text = requirements_path.read_text(encoding="utf-8")
        except OSError:
            return False
        return (
            mode_text == (
                "DEPENDENCY_MODE=static-python-env\n"
                "DEPENDENCY_INSTALL_PHASE=none\n"
                "DEPENDENCY_NETWORK=disabled\n"
                "DEPENDENCY_REPAIR=disabled\n"
            )
            and requirements_text == "\n".join((*DEFAULT_PYTHON_DEPENDENCIES, ""))
        )

    def _dependency_contract_hash(self, root: Path) -> str:
        mode_path = root / "config/chrootctl/dependency-mode.env"
        requirements_path = root / "payload/requirements.txt"
        if not self._regular_file_in_module(mode_path, root) or not self._regular_file_in_module(requirements_path, root):
            return ""
        try:
            digest = hashlib.sha256()
            digest.update(mode_path.read_bytes())
            digest.update(b"\0")
            digest.update(requirements_path.read_bytes())
            return digest.hexdigest()
        except OSError:
            return ""

    def _dependency_readiness(self, root: Path, compatibility: dict[str, Any]) -> dict[str, Any]:
        path = root / "config/chrootctl/dependencies.ready.json"
        compatibility_path = root / "config/chrootctl/compatibility-manifest.json"
        if not self._regular_file_in_module(path, root):
            return {"ready": False, "reason": "readiness_missing_or_unsafe", "path": str(path)}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            return {"ready": False, "reason": "readiness_invalid", "path": str(path), "detail": type(exc).__name__}
        if not isinstance(payload, dict):
            return {"ready": False, "reason": "readiness_invalid", "path": str(path)}
        manifest_hash = self._sha256(compatibility_path) if self._regular_file_in_module(compatibility_path, root) else ""
        recorded_hash = str(payload.get("compatibilityManifestSha256") or "")
        contract_hash = self._dependency_contract_hash(root)
        recorded_contract_hash = str(payload.get("dependencyContractSha256") or "")
        executable = Path(str(payload.get("pythonExecutable") or ""))
        dependencies = payload.get("dependencies")
        deps_ready = isinstance(dependencies, dict) and all(
            self._version_tuple(str(dependencies.get(name) or "")) >= minimum
            for name, minimum in _REQUIRED_DEPENDENCY_MINIMUMS.items()
        )
        executable_ready = executable.is_file() and os.access(executable, os.X_OK)
        ready = (
            payload.get("schemaVersion") == 1
            and bool(payload.get("ready"))
            and isinstance(payload.get("generatedAt"), (int, float))
            and payload.get("dependencyMode") == "static-python-env"
            and bool(manifest_hash)
            and recorded_hash == manifest_hash
            and bool(contract_hash)
            and recorded_contract_hash == contract_hash
            and bool(compatibility.get("valid"))
            and executable_ready
            and deps_ready
        )
        result = dict(payload)
        result["ready"] = bool(ready)
        result["path"] = str(path)
        if not compatibility.get("valid"):
            result["reason"] = "compatibility_manifest_invalid"
        elif not manifest_hash:
            result["reason"] = "compatibility_manifest_missing"
        elif recorded_hash != manifest_hash:
            result["reason"] = "compatibility_manifest_changed"
        elif not contract_hash:
            result["reason"] = "dependency_contract_missing"
        elif recorded_contract_hash != contract_hash:
            result["reason"] = "dependency_contract_changed"
        elif payload.get("dependencyMode") != "static-python-env":
            result["reason"] = "dependency_mode_mismatch"
        elif not isinstance(payload.get("generatedAt"), (int, float)):
            result["reason"] = "readiness_timestamp_missing"
        elif not executable_ready:
            result["reason"] = "python_runtime_missing"
        elif not deps_ready:
            result["reason"] = "dependency_versions_missing"
        elif not bool(payload.get("ready")):
            result.setdefault("reason", "dependencies_not_ready")
        return result

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
    def _version_tuple(value: str) -> tuple[int, ...]:
        out: list[int] = []
        for raw in value.replace("-", ".").split("."):
            digits = "".join(ch for ch in raw if ch.isdigit())
            if not digits:
                break
            out.append(int(digits))
        return tuple(out)

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
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _detect_manager() -> str:
        if Path("/data/adb/ksu").exists() or "KernelSU" in platform.uname().release:
            return "KernelSU"
        if Path("/data/adb/magisk").exists():
            return "Magisk"
        return "unknown"
