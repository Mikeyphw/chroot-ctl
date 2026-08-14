from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrootctl.bridge.previews import PreviewContractStore
from chrootctl.bridge.protocol import BridgeProtocolError
from chrootctl.operations import OperationManager
from chrootctl.operations.journal import OperationJournal


def test_operation_journal_rejects_path_like_operation_ids(tmp_path: Path) -> None:
    journal = OperationJournal(tmp_path / "operations")
    for value in ("../escape", "a/b", "..", "bad.id"):
        with pytest.raises(ValueError):
            journal.load(value)
        with pytest.raises(ValueError):
            journal.request_cancel(value)
        with pytest.raises(ValueError):
            journal.read_events(value)


def test_operation_journal_redacts_persisted_progress_and_result(tmp_path: Path) -> None:
    manager = OperationManager(tmp_path / "operations")
    record = manager.create(kind="test.redaction", title="redaction", request={"password": "secret"})
    completed = manager.execute(
        record,
        lambda progress, cancelled: progress({"message": "Bearer token-value", "access_token": "abc"})
        or {"password": "result-secret"},
    )
    raw = json.loads((manager.journal.records_dir / f"{record.operation_id}.json").read_text(encoding="utf-8"))
    assert raw["request"]["password"] == "<redacted>"
    assert raw["progressDetail"]["access_token"] == "<redacted>"
    assert "token-value" not in raw["progressDetail"]["message"]
    assert raw["resultPayload"]["password"] == "<redacted>"
    assert completed.state == "succeeded"


def test_operation_manager_reads_do_not_recover_stale_records(tmp_path: Path) -> None:
    root = tmp_path / "operations"
    manager = OperationManager(root)
    record = manager.create(kind="test.stale", title="stale")
    record.state = "running"
    record.pid = 999_999_999
    record.process_group_id = 999_999_999
    manager.journal.save(record)

    reopened = OperationManager(root, recover=False)
    assert reopened.get(record.operation_id).state == "running"
    assert reopened.list_recent()[0].state == "running"


def test_event_emitter_failure_cannot_rewrite_success(tmp_path: Path) -> None:
    manager = OperationManager(tmp_path / "operations")
    record = manager.create(kind="test.emit", title="emit")

    def broken_pipe(_event: dict[str, object]) -> None:
        raise BrokenPipeError("reader closed")

    completed = manager.execute(record, lambda progress, cancelled: {"ok": True}, emit=broken_pipe)
    assert completed.state == "succeeded"
    assert manager.get(record.operation_id).state == "succeeded"


def test_cancel_marker_plus_dead_identity_recovers_as_cancelled(tmp_path: Path) -> None:
    root = tmp_path / "operations"
    manager = OperationManager(root)
    record = manager.create(kind="test.cancel", title="cancel")
    record.state = "running"
    record.pid = 999_999_999
    record.process_group_id = 999_999_999
    record.process_start_time = 1
    record.process_boot_id = "not-this-boot"
    manager.journal.save(record)
    manager.journal.request_cancel(record.operation_id)

    manager.recover()
    assert manager.get(record.operation_id).state == "cancelled"


def test_preview_contract_is_one_shot_and_action_bound(tmp_path: Path) -> None:
    store = PreviewContractStore(tmp_path / "previews")
    contract = store.issue(
        preview_operation="chroots.lifecycle.preview",
        action_operation="chroots.upgrade",
        preview_payload={"name": "demo", "action": "upgrade"},
        preview_result={"ok": True, "name": "demo", "installed": True},
    )
    payload = {
        "name": "demo",
        "previewId": contract["previewId"],
        "payloadHash": contract["payloadHash"],
        "resourceRevision": contract["resourceRevision"],
    }
    record = store.verify_fields("chroots.upgrade", payload)
    assert record["previewId"] == contract["previewId"]

    with pytest.raises(BridgeProtocolError) as exc_info:
        store.verify_fields("chroots.upgrade", payload)
    assert exc_info.value.code == "PREVIEW_NOT_FOUND"


def test_preview_contract_rejects_payload_or_action_change(tmp_path: Path) -> None:
    store = PreviewContractStore(tmp_path / "previews")
    contract = store.issue(
        preview_operation="chroots.lifecycle.preview",
        action_operation="chroots.upgrade",
        preview_payload={"name": "demo", "action": "upgrade"},
        preview_result={"ok": True, "name": "demo"},
    )
    with pytest.raises(BridgeProtocolError) as exc_info:
        store.verify_fields(
            "chroots.upgrade",
            {
                "name": "other",
                "previewId": contract["previewId"],
                "payloadHash": contract["payloadHash"],
                "resourceRevision": contract["resourceRevision"],
            },
        )
    assert exc_info.value.code == "PREVIEW_PAYLOAD_CHANGED"

    second = store.issue(
        preview_operation="chroots.lifecycle.preview",
        action_operation="chroots.upgrade",
        preview_payload={"name": "demo", "action": "upgrade"},
        preview_result={"ok": True, "name": "demo"},
    )
    with pytest.raises(BridgeProtocolError) as exc_info:
        store.verify_fields(
            "chroots.remove.execute",
            {
                "name": "demo",
                "previewId": second["previewId"],
                "payloadHash": second["payloadHash"],
                "resourceRevision": second["resourceRevision"],
            },
        )
    assert exc_info.value.code == "PREVIEW_ACTION_MISMATCH"
