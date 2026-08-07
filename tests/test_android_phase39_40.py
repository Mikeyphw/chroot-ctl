from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase39_40_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate-android-phase39-40.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_bridge_capabilities_expose_only_allowlisted_storage_and_logs_queries() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "--dry-run", "capabilities"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["arbitraryShell"] is False
    by_name = {row["name"]: row for row in payload["data"]["operations"]}
    assert by_name["storage.status"]["mode"] == "query"
    assert by_name["storage.status"]["destructive"] is False
    assert by_name["logs.list"]["mode"] == "query"
    assert by_name["logs.list"]["destructive"] is False


def test_snapshot_workspace_routes_restore_through_review_and_confirmation() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    snapshots = source.split("private fun SnapshotPanel", 1)[1].split("private fun UsersPanel", 1)[0]
    row = snapshots.split("private fun FocusedSnapshotRow", 1)[1].split("private const val SNAPSHOT_CREATE_REVIEW_TOKEN", 1)[0]
    assert "SnapshotActionReviewSheet" in snapshots
    assert "operationNeedsSnapshotRecovery" in snapshots
    assert "restoreConfirmation == chroot.name" in snapshots
    assert "snapshotPreviewMatches" in snapshots
    assert "enabled = executeEnabled" in snapshots
    assert "enabled = action != SnapshotWorkspaceAction.Restore" not in snapshots
    assert "onPreviewSnapshotCreate(chroot.name, createSnapshotName)" in snapshots
    assert "onStartSnapshotCreate(chroot.name, createSnapshotName)" in snapshots
    assert "onStartSnapshotRestore" not in row
    assert "onStartSnapshotExport" not in row
    assert "private fun SnapshotRow(" not in snapshots


def test_storage_and_logs_rooms_are_bounded_query_surfaces() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    assert 'OperationSpec("storage.status", "query"' in registry
    assert 'OperationSpec("logs.list", "query"' in registry
    assert "min(tail, 500)" in registry
    assert 'BridgeRequest("logs.list"' in repository
    assert '.put("tail", 200)' in repository
    logs = source.split("private fun LogsPanel", 1)[1].split("private fun logFilterLabel", 1)[0]
    assert "LaunchedEffect(liveTail, filterName, chroot.name)" in logs
    assert "delay(LOG_POLL_INTERVAL_MS)" in logs
    assert "onRefreshServices(chroot.name)" in logs
    assert "servicesPane.targetName != chroot.name" in logs
    storage = source.split("private fun StoragePanel", 1)[1].split("private fun LogsPanel", 1)[0]
    assert "storage_export_support_info" in storage
    assert "supportPane.supportPreview?.ok == true" in storage
    assert "onStartServiceOperation" not in logs


def test_support_export_reuses_the_archive_from_the_accepted_preview() -> None:
    viewmodel = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    assert "supportPreview?.rawJson" in viewmodel
    assert 'JSONObject(raw).optString("archive")' in viewmodel
    assert 'payload.put("archive", archive)' in viewmodel


def test_advanced_room_keeps_preview_and_confirmation_gates() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    advanced = source.split("private fun AdvancedWorkspaceTab", 1)[1].split("private fun BridgePaneError", 1)[0]
    lifecycle = source.split("private fun LifecyclePanel", 1)[1].split("private fun SnapshotPanel", 1)[0]
    assert "capabilities?.protocolVersion" in advanced
    assert "MAX_RAW_PAYLOAD_CHARS" in advanced
    assert "supportPane.supportPreview?.ok == true" in advanced
    assert "supportPane.selectedRepairItemIds.isNotEmpty() && supportPane.repairPreview?.ok == true" in advanced
    assert "removeConfirmation == chroot.name" in lifecycle


def test_phase38_kotlin_warning_is_fixed_without_suppression() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    services = source.split("private fun ServicesPanel", 1)[1].split("private fun userPayload", 1)[0]
    assert "pendingServiceReview" in services
    assert "service to action" in services
    assert "pendingService != null && reviewAction != null" not in services
    assert "@Suppress" not in services


def test_phase37_phase38_and_bridge_shape_promises_remain() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    assert "FocusedServiceRow" in source
    assert "ServiceActionReviewSheet" in source
    assert "FocusedUserRow" in source
    assert "UserActionReviewSheet" in source
    assert 'requireDataOrWrappedArray("checks", "system.status")' in repository
    assert 'requireArrayFromData("users", "items")' in repository
    assert 'requireArrayFromData("services", "items")' in repository
    assert 'requireArrayFromData("snapshots", "items")' in repository


def test_storage_status_shapes_registered_rootfs_and_cache(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from chrootctl.services.chroots import ChrootService

    rootfs = tmp_path / "androidos"
    cache = rootfs / "var" / "cache"
    cache.mkdir(parents=True)
    (rootfs / "etc").mkdir()
    (rootfs / "etc" / "marker").write_bytes(b"rootfs")
    (cache / "cache.bin").write_bytes(b"cache")
    snapshot_dir = tmp_path / ".snapshots"

    class Registry:
        def get(self, name: str):
            return {"name": name, "path": str(rootfs)} if name == "androidos" else None

    config = SimpleNamespace(chroot_base=rootfs, chroot_root=tmp_path, snapshot_dir=snapshot_dir)
    runtime = SimpleNamespace(controller=SimpleNamespace(status=lambda verbose=False: [{"mounted": "yes"}, {"mounted": "no"}]))
    services = SimpleNamespace(
        registry=Registry(),
        config_for=lambda name: config,
        runtime_for=lambda name: runtime,
    )
    summary = ChrootService(services).storage_status("androidos")
    assert summary["rootfsExists"] is True
    assert summary["rootfsBytes"] >= len(b"rootfs") + len(b"cache")
    assert summary["cacheBytes"] == len(b"cache")
    assert summary["mountState"] == "mounted"
    assert summary["mountedCount"] == 1
    assert summary["mountCount"] == 2
    assert summary["snapshotDirectory"] == str(snapshot_dir)
