from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "kotlin" / "com" / "mikeyphw" / "chrootctl"


def _bridge_query(operation: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    request = json.dumps({"protocolVersion": 1, "requestId": "test", "operation": operation, "payload": payload or {}})
    completed = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "--dry-run", "query", "--request-file", "-"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        input=request,
        text=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    return json.loads(completed.stdout)


def test_operations_list_query_is_allowlisted() -> None:
    response = _bridge_query("operations.list")
    assert response["ok"] is True
    assert isinstance(response["data"], list)


def test_android_has_phase_5_room_entities_and_daos() -> None:
    assert (ANDROID / "data" / "ChrootEntities.kt").exists()
    assert (ANDROID / "data" / "ChrootDao.kt").exists()
    database = (ANDROID / "data" / "ChrootCtlDatabase.kt").read_text(encoding="utf-8")
    assert "ChrootEntity::class" in database
    assert "CheckResultEntity::class" in database
    assert "HomeSnapshotEntity::class" in database
    assert "abstract fun chrootDao()" in database
    assert "abstract fun homeSnapshotDao()" in database


def test_android_has_phase_6_feature_screens_not_placeholder_foundation() -> None:
    app = (ANDROID / "ui" / "ChrootCtlApp.kt").read_text(encoding="utf-8")
    assert "HomeScreen(" in app
    assert "ChrootsScreen(" in app
    assert "ActivityScreen(" in app
    assert "ToolsScreen(" in app
    assert "FoundationScreen" not in app
    assert "MainViewModel" in app


def test_android_has_phase_7_home_repository_snapshot() -> None:
    repository = (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
    assert "refreshHome" in repository
    assert 'BridgeRequest("system.dashboard")' in repository
    assert 'BridgeRequest("chroots.list")' in repository
    assert 'BridgeRequest("operations.list")' in repository
    assert "ReadinessRow" in repository
    assert "RecommendedAction" in repository


def test_no_phase_5_7_hardcoded_dangerous_surface() -> None:
    aidl = ROOT / "android" / "app" / "src" / "main" / "aidl" / "com" / "mikeyphw" / "chrootctl" / "root" / "IChrootRootService.aidl"
    aidl_text = aidl.read_text(encoding="utf-8")
    assert "runShell" not in aidl_text
    assert "execute" not in aidl_text
    assert "WebView" not in "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in ANDROID.rglob("*.kt"))
