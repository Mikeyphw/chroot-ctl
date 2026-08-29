from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONTROL_DIR = Path("/data/adb/chrootctl")
DEFAULT_MODULE_ID = "chrootctl-magisk"


@dataclass(frozen=True, slots=True)
class LifecyclePaths:
    control_dir: Path = DEFAULT_CONTROL_DIR
    module_id: str = DEFAULT_MODULE_ID

    @property
    def control_file(self) -> Path:
        return self.control_dir / "control.state"

    @property
    def app_control_file(self) -> Path:
        return self.control_dir / "android-app.enabled"

    @property
    def module_dir(self) -> Path:
        return Path("/data/adb/modules") / self.module_id

    @property
    def module_update_dir(self) -> Path:
        return Path("/data/adb/modules_update") / self.module_id

    @property
    def module_log_file(self) -> Path:
        return self.module_dir / "var/log/chrootctl.log"

    @property
    def install_log_file(self) -> Path:
        return self.module_dir / "runtime/arm64-v8a/runtime-manifest.json"

    @property
    def dependency_log_file(self) -> Path:
        # Retained as a compatibility field for existing clients; native
        # runtime diagnostics are represented by the sealed runtime manifest.
        return self.module_dir / "runtime/arm64-v8a/runtime-manifest.json"


class LifecycleService:
    """Single lifecycle/control surface used by the native Android app and CLI hooks."""

    def __init__(self, paths: LifecyclePaths | None = None) -> None:
        self.paths = paths or LifecyclePaths()

    def status(self) -> dict[str, Any]:
        mode = self.runtime_mode()
        module = self.module_status()
        return {
            "running": bool(module.get("active")),
            "state": "android_app_primary",
            "control_file": str(self.paths.control_file),
            "enabled": self.paths.app_control_file.exists(),
            "mode": mode,
            "module": module,
            "backend": self.backend_status(),
            "python": self.python_status(),  # compatibility alias for older clients
            "logs": {
                "module": str(self.paths.module_log_file),
                "install": str(self.paths.install_log_file),
                "dependencies": str(self.paths.dependency_log_file),
            },
            "checked_at": int(time.time()),
        }

    def runtime_mode(self) -> dict[str, Any]:
        from .module_runtime import ModuleRuntimeStatusService

        control_accessible = os.access(self.paths.control_dir, os.R_OK | os.X_OK)
        module = ModuleRuntimeStatusService().status()
        if control_accessible and module.get("active") is not None:
            return {
                "id": "magisk",
                "label": f"{module.get('manager', 'root')} module",
                "privileged": True,
                "control_accessible": True,
            }
        return {
            "id": "pip",
            "label": "Pip/source",
            "privileged": False,
            "control_accessible": control_accessible,
        }

    def module_status(self) -> dict[str, Any]:
        from .module_runtime import ModuleRuntimeStatusService

        return ModuleRuntimeStatusService().status()

    def backend_status(self) -> dict[str, Any]:
        module = self.module_status()
        active = module.get("active") if isinstance(module.get("active"), dict) else {}
        readiness = active.get("runtimeReadiness") if isinstance(active.get("runtimeReadiness"), dict) else {}
        return {
            "binary": readiness.get("executable"),
            "implementation": "go",
            "version": readiness.get("backendVersion") or readiness.get("pythonPackageVersion"),
            "ready": bool(readiness.get("ready")),
            "reason": readiness.get("reason"),
            "readiness_file": readiness.get("path"),
            "runtime_kind": readiness.get("runtimeKind"),
            "abi": readiness.get("abi"),
        }

    def python_status(self) -> dict[str, Any]:
        """Legacy bridge/UI alias. New clients should consume ``backend``."""
        backend = self.backend_status()
        return {
            "binary": backend.get("binary"),
            "version": backend.get("version"),
            "dependencies_ready": backend.get("ready"),
            "dependencies": [],
            "reason": backend.get("reason"),
            "readiness_file": backend.get("readiness_file"),
            "runtime_kind": backend.get("runtime_kind"),
            "abi": backend.get("abi"),
        }

    @staticmethod
    def _read_pid(path: Path) -> int | None:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, PermissionError, ValueError):
            return None

    @staticmethod
    def _pid_is_running(pid: int | None) -> bool:
        if pid is None:
            return False
        if pid <= 0:
            return False
        proc_path = Path(f"/proc/{pid}")
        if proc_path.exists():
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _read_env_file(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return values
        for line in lines:
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
        return values

    @staticmethod
    def _read_key_values(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return values
        for line in lines:
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        return values

    @staticmethod
    def _read_module_prop(path: Path) -> dict[str, str]:
        return LifecycleService._read_key_values(path)

    @staticmethod
    def _detect_manager() -> str:
        if Path("/data/adb/ksu").exists() or "KernelSU" in platform.uname().release:
            return "KernelSU"
        if Path("/data/adb/magisk").exists():
            return "Magisk"
        return "unknown"
