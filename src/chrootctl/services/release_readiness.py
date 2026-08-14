from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .context import ServiceContainer

_REQUIRED = (
    ("python_pytest", "Python pytest"),
    ("python_mypy", "Python mypy"),
    ("python_compileall", "Python compileall"),
    ("source_package", "Source package validator"),
    ("android_compileDebugKotlin", "Android compileDebugKotlin"),
    ("android_testDebugUnitTest", "Android testDebugUnitTest"),
    ("android_lintDebug", "Android lintDebug"),
    ("module_render", "Module render/tree validator"),
    ("module_zip", "Module ZIP validator"),
    ("module_shell", "Module shell contract"),
    ("source_no_webui", "Retired WebUI regression scan"),
)
_ALLOWED_STATUS = {"pass", "fail", "warn", "pending"}


class ReleaseReadinessService:
    """Consume final-seal evidence without inventing optimistic pass states."""

    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def evidence_path(self) -> Path:
        override = os.environ.get("CHROOTCTL_VALIDATION_RESULTS", "").strip()
        if override:
            return Path(override).expanduser().resolve()
        return (self.services.base_config.database_path.parent / "validation-results.json").expanduser().resolve()

    def status(self) -> dict[str, Any]:
        path = self.evidence_path()
        payload, problem = self._read(path)
        if problem is None:
            identity_problem = self._identity_problem(payload)
            if identity_problem is not None:
                payload, problem = {}, identity_problem
        raw_checks = payload.get("checks") if isinstance(payload, dict) else None
        if not isinstance(raw_checks, dict):
            raw_checks = {}
        checks: list[dict[str, Any]] = []
        for check_id, label in _REQUIRED:
            raw = raw_checks.get(check_id)
            item = raw if isinstance(raw, dict) else {}
            status = str(item.get("status") or "pending").lower()
            if status not in _ALLOWED_STATUS:
                status = "fail"
            recorded_at = item.get("recordedAt")
            if status == "pass" and not isinstance(recorded_at, (int, float)):
                status = "fail"
                item = dict(item)
                item["detail"] = "Passing evidence is missing recordedAt."
            detail = str(item.get("detail") or ("No final-seal evidence recorded." if status == "pending" else ""))
            checks.append({
                "id": check_id,
                "label": label,
                "status": status,
                "detail": detail,
                "command": str(item.get("command") or ""),
                "recordedAt": item.get("recordedAt"),
            })
        passed = sum(item["status"] == "pass" for item in checks)
        failed = sum(item["status"] == "fail" for item in checks)
        pending = sum(item["status"] in {"pending", "warn"} for item in checks)
        return {
            "schemaVersion": 1,
            "evidencePath": str(path),
            "evidencePresent": path.is_file() and problem is None,
            "evidenceProblem": problem,
            "generatedAt": payload.get("generatedAt") if isinstance(payload, dict) else None,
            "sourceCommit": str(payload.get("sourceCommit") or "") if isinstance(payload, dict) else "",
            "checks": checks,
            "passCount": passed,
            "failCount": failed,
            "pendingCount": pending,
            "ready": failed == 0 and pending == 0 and passed == len(checks),
        }

    @staticmethod
    def check(status: dict[str, Any], check_id: str) -> dict[str, Any]:
        for item in status.get("checks", []):
            if isinstance(item, dict) and item.get("id") == check_id:
                return item
        return {"id": check_id, "status": "pending", "detail": "No evidence recorded."}

    @staticmethod
    def _read(path: Path) -> tuple[dict[str, Any], str | None]:
        if not path.is_file() or path.is_symlink():
            return {}, "validation evidence is missing"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            return {}, f"validation evidence is unreadable: {type(exc).__name__}"
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            return {}, "validation evidence schemaVersion must be 1"
        if not isinstance(payload.get("checks"), dict):
            return {}, "validation evidence checks must be an object"
        if not isinstance(payload.get("generatedAt"), (int, float)):
            return {}, "validation evidence generatedAt is required"
        if not str(payload.get("sourceCommit") or "").strip():
            return {}, "validation evidence sourceCommit is required"
        if not str(payload.get("compatibilityManifestSha256") or "").strip():
            return {}, "validation evidence compatibilityManifestSha256 is required"
        return payload, None

    def _identity_problem(self, payload: dict[str, Any]) -> str | None:
        recorded_commit = str(payload.get("sourceCommit") or "").strip()
        current_commit = self._current_source_commit()
        if current_commit and recorded_commit != current_commit:
            return f"validation evidence belongs to source commit {recorded_commit}, current checkout is {current_commit}"
        expected_manifest_hash = self._compatibility_manifest_hash()
        recorded_manifest_hash = str(payload.get("compatibilityManifestSha256") or "").strip()
        if expected_manifest_hash and recorded_manifest_hash != expected_manifest_hash:
            return "validation evidence compatibility manifest does not match the current runtime/source identity"
        return None

    @staticmethod
    def _current_source_commit() -> str:
        repo = Path(__file__).resolve().parents[3]
        if not (repo / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        value = result.stdout.strip()
        return value if result.returncode == 0 and len(value) >= 7 else ""

    def _compatibility_manifest_hash(self) -> str:
        candidates: list[Path] = []
        repo_manifest = Path(__file__).resolve().parents[3] / "docs/release/compatibility-manifest.json"
        candidates.append(repo_manifest)
        try:
            module = self.services.module_runtime().status()
            active = module.get("active") if isinstance(module.get("active"), dict) else {}
            compatibility = active.get("compatibility") if isinstance(active.get("compatibility"), dict) else {}
            path = str(compatibility.get("path") or "")
            if path:
                candidates.append(Path(path))
        except Exception:
            pass
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                return hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
        return ""
