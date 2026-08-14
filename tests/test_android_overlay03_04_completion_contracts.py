from __future__ import annotations

from pathlib import Path


def test_android_exposes_explicit_backend_reconciliation_without_mutating_reads() -> None:
    repo = Path(__file__).resolve().parents[1]
    aidl = (repo / "android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl").read_text(encoding="utf-8")
    root_service = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt").read_text(encoding="utf-8")
    root_client = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt").read_text(encoding="utf-8")
    repository = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt").read_text(encoding="utf-8")
    service = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt").read_text(encoding="utf-8")

    assert "String reconcileOperation(String operationId);" in aidl
    assert 'listOf("reconcile", operationId)' in root_service
    assert "it.reconcileOperation(operationId)" in root_client
    assert "rootClient.reconcileOperation(operationId)" in repository
    assert "repository.reconcileOperation(operationId)" in service
    assert "rootClient.operationState(operationId)" in repository


def test_android_forwards_preview_contract_for_every_existing_stateful_review_flow() -> None:
    repo = Path(__file__).resolve().parents[1]
    view_model = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt").read_text(encoding="utf-8")
    app = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt").read_text(encoding="utf-8")
    repository = (repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt").read_text(encoding="utf-8")

    for operation in (
        "snapshots.create",
        "snapshots.restore",
        "snapshots.export",
        "users.add",
        "users.remove",
        "users.sync_uid_gid",
        "users.set_shell",
        "users.set_sudo",
        "users.set_password",
        "transfer.export",
        "smoke.run",
    ):
        assert f'"{operation}"' in view_model
    assert '"chroots.$action"' in view_model
    assert '"services.$action"' in view_model
    assert "userOperationPayloadJson(operation, payload)" in app
    assert "serviceOperationPayloadJson(operation, payload)" in app
    assert 'rootClient.preview(BridgeRequest("smoke.preview", payload).toJson())' in repository
