from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrootctl.bridge.dispatcher import BridgeDispatcher
from chrootctl.bridge.protocol import BridgeProtocolError, BridgeRequest
from chrootctl.bridge.redaction import redact_value
from chrootctl.operations import OperationManager
from chrootctl.services import create_service_container


def _services(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "chroot_root": str(tmp_path / "chroots"),
                "database_path": str(tmp_path / "state" / "chroots.sqlite3"),
                "snapshot_dir": str(tmp_path / "state" / "snapshots"),
                "log_file": str(tmp_path / "state" / "chrootctl.log"),
                "service_dirs": [str(tmp_path / "state" / "services")],
                "service_state_dir": str(tmp_path / "state" / "run" / "services"),
                "service_log_dir": str(tmp_path / "state" / "logs" / "services"),
            }
        ),
        encoding="utf-8",
    )
    return create_service_container(config, dry_run=True)


def test_bridge_protocol_rejects_unknown_versions_and_shell_operation_names() -> None:
    with pytest.raises(BridgeProtocolError, match="not supported"):
        BridgeRequest.from_mapping({"protocolVersion": 2, "requestId": "request", "operation": "system.dashboard", "payload": {}})

    with pytest.raises(BridgeProtocolError, match="safe allowlisted identifier"):
        BridgeRequest.from_mapping(
            {
                "protocolVersion": 1,
                "requestId": "request",
                "operation": "system.dashboard; rm -rf /",
                "payload": {},
            }
        )


def test_bridge_capabilities_forbid_arbitrary_shell(tmp_path: Path) -> None:
    dispatcher = BridgeDispatcher(_services(tmp_path))
    capabilities = dispatcher.capabilities()
    assert capabilities["protocolVersion"] == 1
    assert capabilities["arbitraryShell"] is False
    names = {item["name"] for item in capabilities["operations"]}
    assert {"system.dashboard", "chroots.list", "system.refresh"} <= names


def test_bridge_query_and_persistent_refresh_operation(tmp_path: Path) -> None:
    dispatcher = BridgeDispatcher(_services(tmp_path))
    query = BridgeRequest.from_mapping(
        {"protocolVersion": 1, "requestId": "list-1", "operation": "chroots.list", "payload": {}}
    )
    response = dispatcher.query(query)
    assert response.ok
    assert response.data == []

    events: list[dict[str, object]] = []
    refresh = BridgeRequest.from_mapping(
        {"protocolVersion": 1, "requestId": "refresh-1", "operation": "system.refresh", "payload": {}}
    )
    assert dispatcher.run(refresh, events.append) == 0
    operation_ids = {str(event.get("operationId")) for event in events if event.get("operationId")}
    assert len(operation_ids) == 1
    operation = dispatcher.operation(operation_ids.pop())
    assert operation.ok
    assert operation.data["state"] == "succeeded"
    assert operation.data["progressPercent"] == 100


def test_operation_journal_survives_manager_recreation(tmp_path: Path) -> None:
    root = tmp_path / "operations"
    manager = OperationManager(root)
    record = manager.create(kind="test.operation", title="Test operation")
    completed = manager.execute(
        record,
        lambda progress, cancelled: progress({"phase": "test", "percent": 50, "message": "Testing"}) or {"ok": True},
    )
    assert completed.state == "succeeded"

    reopened = OperationManager(root).get(record.operation_id)
    assert reopened.state == "succeeded"
    assert reopened.result_payload == {"ok": True}
    assert any(event["type"] == "operation_progress" for event in reopened.progress_events)


def test_redaction_removes_persistent_secrets() -> None:
    redacted = redact_value(
        {
            "password": "hunter2",
            "nested": {"access_token": "abc", "message": "Bearer secret-value"},
        }
    )
    assert redacted["password"] == "<redacted>"
    assert redacted["nested"]["access_token"] == "<redacted>"
    assert redacted["nested"]["message"] == "Bearer <redacted>"


def test_android_root_contract_contains_no_arbitrary_shell_surface() -> None:
    repo = Path(__file__).resolve().parents[1]
    aidl = (repo / "android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl").read_text(encoding="utf-8")
    service = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt").read_text(encoding="utf-8")
    process = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt").read_text(encoding="utf-8")
    combined = f"{aidl}\n{service}\n{process}".lower()
    assert "runshell" not in combined
    assert "executecommand" not in combined
    assert "runtime.exec" not in combined
    assert "processbuilder(command)" in process.lower()
    assert "String query(String requestJson);" in aidl
    assert "String startOperation(String requestJson, in ParcelFileDescriptor output);" in aidl


def test_every_web_route_is_named_in_parity_matrix() -> None:
    repo = Path(__file__).resolve().parents[1]
    matrix = (repo / "docs/android/WEBUI_PARITY_MATRIX.md").read_text(encoding="utf-8")
    route_files = sorted((repo / "src/chrootctl/web/routes").glob("*.py"))
    for route in route_files:
        if route.name == "__init__.py":
            continue
        assert route.name in matrix, f"Missing parity mapping for {route.name}"
