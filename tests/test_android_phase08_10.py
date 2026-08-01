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
    assert completed.stdout.strip(), completed.stderr
    return json.loads(completed.stdout)


def test_operations_get_is_allowlisted_and_validates_identifier() -> None:
    response = _bridge_query("operations.get", {})
    assert response["ok"] is False
    assert response["error"]["code"] == "MISSING_OPERATION_ID"


def test_chroots_screen_has_detail_refresh_contract() -> None:
    text = (ANDROID / "ui" / "chroots" / "ChrootsScreen.kt").read_text(encoding="utf-8")
    assert "ChrootDetail" in text
    assert "onRefreshDetail" in text
    assert "CheckSummary" in text
    assert "selected" in text


def test_activity_screen_has_operation_timeline_contract() -> None:
    text = (ANDROID / "ui" / "activity" / "ActivityScreen.kt").read_text(encoding="utf-8")
    assert "OperationDetail" in text
    assert "OperationEventSummary" in text
    assert "operation_event_line" in text
    assert "MAX_VISIBLE_EVENTS" in text


def test_foreground_operation_service_is_fixed_scope() -> None:
    service = (ANDROID / "operations" / "ChrootOperationService.kt").read_text(encoding="utf-8")
    notifier = (ANDROID / "operations" / "OperationNotificationController.kt").read_text(encoding="utf-8")
    manifest = (ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "startSystemRefresh" in service
    assert "cancelOperation" in service
    assert "ServiceCompat.startForeground" in notifier
    assert ".operations.ChrootOperationService" in manifest
    assert 'android:foregroundServiceType="dataSync"' in manifest
    assert "runShell" not in service + notifier
    assert "executeArbitraryCommand" not in service + notifier


def test_repository_records_streamed_operation_events() -> None:
    repository = (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
    assert "startSystemRefresh" in repository
    assert "recordOperationEvent" in repository
    assert "toOperationEventEntity" in repository
    assert "refreshOperationDetail" in repository
    assert "operationEvents" in repository
    assert 'BridgeRequest("system.status"' in repository
    assert 'BridgeRequest("system.doctor"' in repository
