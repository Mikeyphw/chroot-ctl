from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from chrootctl.bridge.cli import build_parser
from chrootctl.bridge.previews import (
    PREVIEW_REQUIRED_OPERATIONS,
    action_operation_for_preview,
    preview_payload_for_action,
)
from chrootctl.bridge.registry import _catalog_entry_payload, _strict_repair_decisions
from chrootctl.bridge.protocol import BridgeProtocolError
from chrootctl.operations import OperationManager
from chrootctl.system import ProcessIdentity, process_identity_matches


@pytest.mark.parametrize(
    "operation",
    [
        "chroots.start",
        "chroots.restart",
        "snapshots.create",
        "snapshots.export",
        "users.add",
        "users.sync_uid_gid",
        "users.set_shell",
        "users.set_sudo",
        "services.start",
        "services.stop",
        "services.restart",
        "services.enable",
        "services.disable",
        "transfer.export",
        "smoke.run",
    ],
)
def test_completion_preview_scope_covers_previously_unbound_actions(operation: str) -> None:
    assert operation in PREVIEW_REQUIRED_OPERATIONS
    assert preview_payload_for_action(operation, {}) is not None


def test_preview_routes_bind_lifecycle_user_service_snapshot_and_export_actions() -> None:
    assert action_operation_for_preview("chroots.lifecycle.preview", {"action": "start"}) == "chroots.start"
    assert action_operation_for_preview("snapshots.preview", {"action": "create"}) == "snapshots.create"
    assert action_operation_for_preview("users.preview", {"action": "set_shell"}) == "users.set_shell"
    assert action_operation_for_preview("services.preview", {"action": "disable"}) == "services.disable"
    assert action_operation_for_preview("transfer.preview_export", {}) == "transfer.export"
    assert action_operation_for_preview("chroots.export", {}) == "transfer.export"
    assert action_operation_for_preview("smoke.preview", {}) == "smoke.run"


def test_preview_recompute_preserves_preview_family_that_issued_approval() -> None:
    operation, payload = preview_payload_for_action(
        "transfer.export",
        {"name": "demo", "archive": "/tmp/demo.tar.zst"},
        preview_operation="chroots.export",
    ) or (None, None)
    assert operation == "chroots.export"
    assert payload == {"name": "demo", "archive": "/tmp/demo.tar.zst"}


def test_catalog_preview_payload_is_bound_to_script_content_hash() -> None:
    first = _catalog_entry_payload(SimpleNamespace(kind="tool", name="demo", script="demo.sh", script_text="echo one\n"))
    second = _catalog_entry_payload(SimpleNamespace(kind="tool", name="demo", script="demo.sh", script_text="echo two\n"))
    assert first["scriptSha256"] != second["scriptSha256"]


def test_repair_decisions_fail_closed_on_invalid_or_duplicate_items() -> None:
    with pytest.raises(BridgeProtocolError):
        _strict_repair_decisions(["not-an-object"], required=True)
    with pytest.raises(BridgeProtocolError):
        _strict_repair_decisions([{"item_id": "a", "action": "skip"}, {"item_id": "a", "action": "skip"}], required=True)


def test_explicit_reconcile_mutates_only_when_called(tmp_path: Path) -> None:
    manager = OperationManager(tmp_path / "operations")
    record = manager.create(kind="test.reconcile", title="reconcile")
    record.state = "running"
    record.pid = 999_999_999
    record.process_group_id = 999_999_999
    record.process_start_time = 1
    record.process_boot_id = "dead-boot"
    manager.journal.save(record)

    assert manager.get(record.operation_id).state == "running"
    assert manager.reconcile(record.operation_id).state == "interrupted"


def test_weak_process_identity_is_never_signal_safe() -> None:
    assert not process_identity_matches(ProcessIdentity(pid=1, process_group_id=1, start_time_ticks=None, boot_id=None))


def test_bridge_cli_exposes_explicit_reconcile_command() -> None:
    args = build_parser().parse_args(["reconcile", "abcdef1234567890"])
    assert args.command == "reconcile"
    assert args.operation_id == "abcdef1234567890"
