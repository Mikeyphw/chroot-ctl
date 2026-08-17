from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .context import ServiceContainer

_REQUIRED = (
    ("python_pytest", "Python pytest"),
    ("python_mypy", "Python mypy"),
    ("python_compileall", "Python compileall"),
    ("android_contract_validators", "Android source-contract validators"),
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
_ALLOWED_PASS_PROVENANCE = {"subprocess", "deduplicated-subprocess"}
_REQUIRED_IDS = frozenset(item[0] for item in _REQUIRED)


def _is_git_oid(value: object) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(ch in "0123456789abcdef" for ch in text)


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


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
            if status == "pass":
                provenance = str(item.get("provenance") or "")
                exit_code = item.get("exitCode")
                command = str(item.get("command") or "").strip()
                if not isinstance(recorded_at, (int, float)):
                    status = "fail"; item = dict(item); item["detail"] = "Passing evidence is missing recordedAt."
                elif exit_code != 0:
                    status = "fail"; item = dict(item); item["detail"] = "Passing evidence is missing a proven exitCode 0."
                elif provenance not in _ALLOWED_PASS_PROVENANCE:
                    status = "fail"; item = dict(item); item["detail"] = "Passing evidence has invalid provenance."
                elif not command:
                    status = "fail"; item = dict(item); item["detail"] = "Passing evidence is missing command/task provenance."
            detail = str(item.get("detail") or ("No final-seal evidence recorded." if status == "pending" else ""))
            checks.append({
                "id": check_id, "label": label, "status": status, "detail": detail,
                "command": str(item.get("command") or ""), "provenance": str(item.get("provenance") or ""),
                "exitCode": item.get("exitCode"), "recordedAt": item.get("recordedAt"),
            })
        passed = sum(item["status"] == "pass" for item in checks)
        failed = sum(item["status"] == "fail" for item in checks)
        pending = sum(item["status"] in {"pending", "warn"} for item in checks)
        return {
            "schemaVersion": 2,
            "evidencePath": str(path),
            "evidencePresent": path.is_file() and problem is None,
            "evidenceProblem": problem,
            "generatedAt": payload.get("generatedAt") if isinstance(payload, dict) else None,
            "validationRunId": str(payload.get("validationRunId") or "") if isinstance(payload, dict) else "",
            "sourceCommit": str(payload.get("sourceCommit") or "") if isinstance(payload, dict) else "",
            "sourceTree": str(payload.get("sourceTree") or "") if isinstance(payload, dict) else "",
            "validatedTree": str(payload.get("validatedTree") or "") if isinstance(payload, dict) else "",
            "checks": checks, "passCount": passed, "failCount": failed, "pendingCount": pending,
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
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            return {}, f"validation evidence metadata is unreadable: {type(exc).__name__}"
        if mode & 0o077:
            return {}, "validation evidence permissions must not grant group/other access"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            return {}, f"validation evidence is unreadable: {type(exc).__name__}"
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 2:
            return {}, "validation evidence schemaVersion must be 2"
        checks = payload.get("checks")
        if not isinstance(checks, dict):
            return {}, "validation evidence checks must be an object"
        if set(checks) != _REQUIRED_IDS:
            missing = sorted(_REQUIRED_IDS - set(checks)); extra = sorted(set(checks) - _REQUIRED_IDS)
            return {}, f"validation evidence check set mismatch; missing={missing} extra={extra}"
        for key in ("generatedAt", "validationStartedAt", "validationCompletedAt"):
            if not _finite_number(payload.get(key)):
                return {}, f"validation evidence {key} must be a finite timestamp"
        started = float(payload["validationStartedAt"]); completed = float(payload["validationCompletedAt"]); generated = float(payload["generatedAt"])
        if completed < started or generated != completed:
            return {}, "validation evidence run timestamps are inconsistent"
        if not str(payload.get("validationRunId") or "").strip():
            return {}, "validation evidence validationRunId is required"
        for key in ("sourceCommit", "sourceTree", "validatedTree"):
            if not _is_git_oid(payload.get(key)):
                return {}, f"validation evidence {key} must be an exact lowercase 40-hex Git object id"
        if payload.get("sourceTree") == payload.get("validatedTree"):
            return {}, "validation evidence validatedTree must differ from the pre-overlay sourceTree"
        if not _is_sha256(payload.get("compatibilityManifestSha256")):
            return {}, "validation evidence compatibilityManifestSha256 must be an exact lowercase SHA-256"
        for check_id in _REQUIRED_IDS:
            item = checks.get(check_id)
            if not isinstance(item, dict):
                return {}, f"validation evidence check {check_id} must be an object"
            if str(item.get("status") or "").lower() == "pass":
                gate_started = item.get("startedAt"); gate_finished = item.get("finishedAt"); recorded_at = item.get("recordedAt")
                if not all(_finite_number(value) for value in (gate_started, gate_finished, recorded_at)):
                    return {}, f"validation evidence passing check {check_id} has invalid timing provenance"
                gs = float(gate_started); gf = float(gate_finished); ra = float(recorded_at)
                if not (started <= gs <= gf <= completed and gf <= ra <= completed):
                    return {}, f"validation evidence passing check {check_id} has inconsistent timing provenance"
                provenance = str(item.get("provenance") or "")
                if provenance == "deduplicated-subprocess":
                    parent = str(item.get("derivedFrom") or "")
                    if parent not in _REQUIRED_IDS or parent == check_id:
                        return {}, f"validation evidence passing check {check_id} has invalid derivedFrom provenance"
        return payload, None

    def _identity_problem(self, payload: dict[str, Any]) -> str | None:
        recorded_commit = str(payload.get("sourceCommit") or "").strip()
        recorded_source_tree = str(payload.get("sourceTree") or "").strip()
        recorded_validated_tree = str(payload.get("validatedTree") or "").strip()
        current_commit = self._current_source_commit()
        if (self._repo_root() / ".git").exists() and not current_commit:
            return "validation evidence source identity cannot be verified because Git HEAD is unavailable"
        if current_commit:
            recorded_commit_tree = self._tree_for_commit(recorded_commit)
            if recorded_commit_tree != recorded_source_tree:
                return "validation evidence sourceCommit does not resolve to the recorded pre-overlay sourceTree"
            current_worktree_tree = self._current_worktree_tree()
            if not current_worktree_tree or current_worktree_tree != recorded_validated_tree:
                return "validation evidence validatedTree does not match the exact current tracked/untracked worktree"
            current_tree = self._current_source_tree()
            if current_commit == recorded_commit:
                if current_tree != recorded_source_tree:
                    return "validation evidence pre-commit HEAD tree does not match the recorded sourceTree"
            else:
                current_parent = self._current_source_parent()
                if current_parent != recorded_commit or current_tree != recorded_validated_tree:
                    return (
                        f"validation evidence belongs to source commit {recorded_commit}, current checkout is {current_commit}, "
                        "and it is not the single Devtool commit of the exact validated tree"
                    )
        expected_manifest_hash = self._compatibility_manifest_hash()
        recorded_manifest_hash = str(payload.get("compatibilityManifestSha256") or "").strip()
        if not _is_sha256(expected_manifest_hash):
            return "validation evidence compatibility manifest identity cannot be verified"
        if recorded_manifest_hash != expected_manifest_hash:
            return "validation evidence compatibility manifest does not match the current runtime/source identity"
        return None

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]

    @classmethod
    def _git_value(cls, *args: str, env: dict[str, str] | None = None) -> str:
        repo = cls._repo_root()
        if not (repo / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=5, check=False, env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        value = result.stdout.strip()
        return value if result.returncode == 0 else ""

    @classmethod
    def _current_source_commit(cls) -> str:
        value = cls._git_value("rev-parse", "HEAD")
        return value if len(value) == 40 else ""

    @classmethod
    def _current_source_tree(cls) -> str:
        value = cls._git_value("rev-parse", "HEAD^{tree}")
        return value if len(value) == 40 else ""

    @classmethod
    def _current_source_parent(cls) -> str:
        value = cls._git_value("rev-parse", "HEAD^")
        return value if len(value) == 40 else ""

    @classmethod
    def _tree_for_commit(cls, commit: str) -> str:
        if len(commit) != 40:
            return ""
        value = cls._git_value("rev-parse", f"{commit}^{{tree}}")
        return value if len(value) == 40 else ""

    @classmethod
    def _current_worktree_tree(cls) -> str:
        repo = cls._repo_root()
        if not (repo / ".git").exists():
            return ""
        fd, index_name = tempfile.mkstemp(prefix="chrootctl-readiness-index-")
        os.close(fd)
        index = Path(index_name)
        try:
            index.unlink(missing_ok=True)
            env = dict(os.environ); env["GIT_INDEX_FILE"] = str(index)
            if not cls._git_value("read-tree", "HEAD", env=env) and not index.exists():
                return ""
            add = subprocess.run(["git", "-C", str(repo), "add", "-A", "--", "."], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, timeout=10, check=False)
            if add.returncode != 0:
                return ""
            value = cls._git_value("write-tree", env=env)
            return value if len(value) == 40 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
        finally:
            index.unlink(missing_ok=True)

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
