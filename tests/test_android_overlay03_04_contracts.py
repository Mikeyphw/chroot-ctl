from __future__ import annotations

from pathlib import Path


def test_android_operation_service_persists_request_and_reconciles_stream() -> None:
    repo = Path(__file__).resolve().parents[1]
    service = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt").read_text(encoding="utf-8")
    repository = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt").read_text(encoding="utf-8")
    root_client = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt").read_text(encoding="utf-8")
    notification = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/OperationNotificationController.kt").read_text(encoding="utf-8")

    assert "KEY_REQUEST_ID" in service
    assert "KEY_PAYLOAD" not in service
    assert "discoverOperationId" in service
    assert "findOperationIdByRequestId" in repository
    assert "reconcileUntilTerminal" in service
    assert "bridge_stream_interrupted" in root_client
    assert "operationState(knownOperationId)" in root_client
    assert "STOP_FOREGROUND_DETACH" in service
    assert "EXTRA_OPEN_OPERATION_ID" in notification


def test_android_preview_contract_is_forwarded_for_destructive_actions() -> None:
    repo = Path(__file__).resolve().parents[1]
    view_model = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt").read_text(encoding="utf-8")
    models = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt").read_text(encoding="utf-8")

    for field in ("previewId", "payloadHash", "resourceRevision", "actionOperation"):
        assert field in models
    for operation in (
        "install.run",
        "chroots.remove.execute",
        "snapshots.restore",
        "users.remove",
        "users.set_password",
        "catalog.apply",
        "transfer.import",
        "artifacts.cleanup",
        "support.bundle",
        "system.module_build",
        "repair.apply",
        "cleanup.temp",
    ):
        assert f'"{operation}"' in view_model
