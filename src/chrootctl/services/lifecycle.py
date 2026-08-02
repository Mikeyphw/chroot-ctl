from __future__ import annotations

import os
import platform
import subprocess
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
        return self.module_dir / "config/chrootctl/python-detection.txt"

    @property
    def dependency_log_file(self) -> Path:
        return self.module_dir / "config/chrootctl/dependency-bootstrap.log"


class LifecycleService:
    """Single lifecycle/control surface used by the native Android app and CLI hooks."""

    def __init__(self, paths: LifecyclePaths | None = None) -> None:
        self.paths = paths or LifecyclePaths()

    def status(self) -> dict[str, Any]:
        mode = self.runtime_mode()
        return {
            "running": self.paths.module_dir.exists() or self.paths.module_update_dir.exists(),
            "state": "android_app_primary",
            "control_file": str(self.paths.control_file),
            "enabled": self.paths.app_control_file.exists(),
            "mode": mode,
            "module": self.module_status(),
            "python": self.python_status(),
            "logs": {
                "module": str(self.paths.module_log_file),
                "install": str(self.paths.install_log_file),
                "dependencies": str(self.paths.dependency_log_file),
            },
            "checked_at": int(time.time()),
        }

    def runtime_mode(self) -> dict[str, Any]:
        control_accessible = os.access(self.paths.control_dir, os.R_OK | os.X_OK)
        module_present = self.paths.module_dir.exists() or self.paths.module_update_dir.exists()
        if control_accessible and module_present:
            return {
                "id": "magisk",
                "label": "Magisk module",
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
        module_dir = self.paths.module_dir
        update_dir = self.paths.module_update_dir
        prop = self._read_module_prop(module_dir / "module.prop")
        return {
            "id": prop.get("id", self.paths.module_id),
            "name": prop.get("name", "chrootctl"),
            "version": prop.get("version"),
            "version_code": prop.get("versionCode"),
            "path": str(module_dir),
            "installed": module_dir.exists(),
            "pending_update": update_dir.exists(),
            "manager": self._detect_manager(),
        }

    def python_status(self) -> dict[str, Any]:
        env = self._read_env_file(self.paths.module_dir / "config/chrootctl/python.env")
        detection = self._read_key_values(self.paths.module_dir / "config/chrootctl/python-detection.txt")
        missing = detection.get("missing", "")
        return {
            "binary": env.get("PYTHON_BIN"),
            "version": env.get("PYTHON_VERSION"),
            "executable": env.get("PYTHON_EXECUTABLE"),
            "prefix": env.get("PYTHON_PREFIX"),
            "ld_library_path": env.get("PYTHON_LD_LIBRARY_PATH"),
            "dependencies_ready": not bool(missing and missing != "none"),
            "missing": missing.split() if missing and missing != "none" else [],
            "detection_file": str(self.paths.module_dir / "config/chrootctl/python-detection.txt"),
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
