#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise AssertionError(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    chroots = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    viewmodel = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    registry = read("src/chrootctl/bridge/registry.py")
    chroot_service = read("src/chrootctl/services/chroots.py")
    dispatcher = read("src/chrootctl/bridge/dispatcher.py")
    workflow_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicyTest.kt")
    phase37_validator = read("scripts/validate-android-phase37.py")
    phase38_validator = read("scripts/validate-android-phase38.py")
    doc = read("docs/android/PHASE_39_40_SNAPSHOTS_STORAGE_LOGS_ADVANCED.md")
    strings_path = ROOT / "android/app/src/main/res/values/strings.xml"
    ET.parse(strings_path)
    strings = strings_path.read_text(encoding="utf-8")

    # Workspace shape.
    for token in (
        "ChrootWorkspaceTab.Snapshots",
        "ChrootWorkspaceTab.Storage",
        "ChrootWorkspaceTab.Logs",
        "ChrootWorkspaceTab.Advanced",
        'ChrootWorkspaceTab.Storage -> "storage"',
        'ChrootWorkspaceTab.Logs -> "logs"',
    ):
        require(token in policy, f"Phase 39-40 workspace policy missing {token}")
    require("StoragePanel(" in chroots and "LogsPanel(" in chroots, "Storage/Logs rooms are not routed from the selected-chroot workspace")
    require("chrootListIsWorkspaceLauncherOnly(): Boolean = true" in policy, "top-level Chroots launcher promise regressed")

    # Snapshot recovery room.
    snapshots = chroots.split("private fun SnapshotPanel", 1)[1].split("private fun UsersPanel", 1)[0]
    for token in (
        "SnapshotActionReviewSheet",
        "FocusedSnapshotRow",
        "operationNeedsSnapshotRecovery",
        "snapshot_recovery_title",
        "snapshot_restore_confirmation_label",
        'onPreviewSnapshotAction(chroot.name, it.name, "restore")',
        "restoreConfirmation == chroot.name",
        "snapshotPreviewMatches",
        "previewAction = pane.previewAction",
        "previewSnapshot = pane.previewSnapshot",
        "enabled = executeEnabled",
        "onStartSnapshotExport",
    ):
        require(token in snapshots, f"focused snapshot recovery workspace missing {token}")
    require("private fun SnapshotRow(" not in snapshots, "legacy per-snapshot execution row remains")
    focused_snapshot = snapshots.split("private fun FocusedSnapshotRow", 1)[1].split("private const val SNAPSHOT_CREATE_REVIEW_TOKEN", 1)[0]
    require("onStartSnapshotRestore" not in focused_snapshot and "onStartSnapshotExport" not in focused_snapshot, "snapshot row executes mutations instead of opening review")
    require("failedOperation" in snapshots and "snapshots.first()" in snapshots, "failed-operation recovery entry point is missing")
    require("enabled = action != SnapshotWorkspaceAction.Restore" not in snapshots, "snapshot execution can bypass the exact preview gate")
    require("onPreviewSnapshotCreate(chroot.name, createSnapshotName)" in snapshots, "snapshot create preview does not bind the stable reviewed snapshot name")
    require("onStartSnapshotCreate(chroot.name, createSnapshotName)" in snapshots, "snapshot create execution does not reuse the previewed snapshot name")

    # Storage is a structured, allowlisted query only.
    for token in (
        'OperationSpec("storage.status", "query"',
        "def _storage_status",
        "def storage_status",
        '"rootfsBytes"',
        '"cacheBytes"',
        '"freeBytes"',
        '"mountState"',
        '"snapshotDirectory"',
    ):
        require(token in registry or token in chroot_service, f"storage bridge contract missing {token}")
    require('BridgeRequest("storage.status"' in repository, "Android Storage room does not use storage.status")
    for token in ("data class StorageSummary", "rootfsExists", "cacheBytes", "mountedCount", "snapshotDirectory"):
        require(token in models, f"storage model missing {token}")
    storage = chroots.split("private fun StoragePanel", 1)[1].split("private fun LogsPanel", 1)[0]
    for token in (
        "storage_missing_rootfs",
        "storage_stale_warning",
        "storage_snapshot_footprint",
        "formatStorageBytes",
        "onOpenAdvanced",
        "onPreviewSupportBundle",
        "onStartSupportBundle",
        "supportPane.supportPreview?.ok == true",
        "storage_export_support_info",
    ):
        require(token in storage, f"Storage room missing {token}")

    # Logs are bounded and read-only, with polling cancelled by composition lifecycle.
    require('OperationSpec("logs.list", "query"' in registry, "logs.list is not an allowlisted query")
    logs_handler = registry.split("def _logs_list", 1)[1].split("def _required_username", 1)[0]
    require("min(tail, 500)" in logs_handler and "max(20" in logs_handler, "backend log tail is not bounded")
    require('{None, "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}' in logs_handler, "backend log level allowlist missing")
    require('BridgeRequest("logs.list"' in repository and '.put("tail", 200)' in repository, "Android logs query is not bounded to 200 lines")
    logs = chroots.split("private fun LogsPanel", 1)[1].split("private fun logFilterLabel", 1)[0]
    for token in (
        "LaunchedEffect(liveTail, filterName, chroot.name)",
        "delay(LOG_POLL_INTERVAL_MS)",
        "LogWorkspaceFilter.entries",
        "onRefreshServices",
        "servicesPane.targetName != chroot.name",
        "onRefreshServiceDetail",
        "MAX_VISIBLE_LOG_LINES",
    ):
        require(token in logs, f"Logs room missing {token}")
    require("onStartServiceOperation" not in logs, "Logs room can mutate services")
    require("LOG_POLL_INTERVAL_MS = 5_000L" in chroots, "Logs polling interval is not explicitly bounded")
    require('LogWorkspaceFilter.Warning -> "WARNING"' in policy and 'LogWorkspaceFilter.Error -> "ERROR"' in policy, "log filter bridge mapping regressed")

    # Advanced technical room and danger gates.
    advanced = chroots.split("private fun AdvancedWorkspaceTab", 1)[1].split("private fun BridgePaneError", 1)[0]
    for token in (
        "LifecyclePanel",
        "capabilities?.protocolVersion",
        "capabilities?.backendVersion",
        "capabilities?.arbitraryShell",
        "MAX_RAW_PAYLOAD_CHARS",
        "onPreviewSupportBundle",
        "supportPane.supportPreview?.ok == true",
        "onPreviewRepair",
        "supportPane.selectedRepairItemIds.isNotEmpty() && supportPane.repairPreview?.ok == true",
        "onStartRepair",
    ):
        require(token in advanced, f"Advanced workspace missing {token}")
    lifecycle = chroots.split("private fun LifecyclePanel", 1)[1].split("private fun SnapshotPanel", 1)[0]
    require("removeConfirmation == chroot.name" in lifecycle, "destructive chroot removal exact-name confirmation regressed")

    # Phase 38 warning closure must be structural, not a suppression.
    services = chroots.split("private fun ServicesPanel", 1)[1].split("private fun userPayload", 1)[0]
    require("pendingServiceReview" in services and "service to action" in services, "service review nullability was not paired structurally")
    require("pendingService != null && reviewAction != null" not in services, "Phase 38 always-true condition remains")
    require("@Suppress" not in services, "Phase 38 warning was suppressed instead of fixed")

    # Existing Phase 37 Services and Phase 38 Users promises stay intact.
    for token in ("FocusedServiceRow", "ServiceActionReviewSheet", "serviceWorkspaceFilters().forEach", "serviceMatchesWorkspaceFilter"):
        require(token in services, f"Phase 37 Services workspace regressed: {token}")
    users = chroots.split("private fun UsersPanel", 1)[1].split("private fun ServicesPanel", 1)[0]
    for token in ("UserWorkspaceFilter.Managed", "FocusedUserRow", "UserActionReviewSheet", "action_show_system_users", "reviewUsername(reviewUserToken)"):
        require(token in users, f"Phase 38 Users workspace regressed: {token}")
    require("Phase 37 focused services workspace validation passed" in phase37_validator, "Phase 37 validator disappeared")
    require("Phase 38 focused users workspace validation passed" in phase38_validator, "Phase 38 validator disappeared")

    # Bridge shape and app wiring.
    for token in (
        'requireDataOrWrappedArray("checks", "system.status")',
        'requireDataOrWrappedArray("checks", "system.doctor")',
        'requireArrayFromData("users", "items")',
        'requireArrayFromData("services", "items")',
        'requireArrayFromData("snapshots", "items")',
    ):
        require(token in repository, f"Phase 35-36 bridge adapter missing: {token}")
    for token in (
        "fun refreshStorage(name: String)",
        "fun refreshLogs(name: String, level: String? = null)",
        "fun previewSnapshotCreate(name: String, snapshot: String)",
        "fun snapshotCreatePayloadJson(name: String, snapshot: String)",
        "previewAction = normalizedAction",
        "previewSnapshot = snapshot",
        "storagePane",
        "logsPane",
    ):
        require(token in viewmodel, f"ViewModel Phase 39-40 wiring missing {token}")
    require('.withPreviewContract(systemSupportPane.value.supportPreview, "support.bundle")' in viewmodel, "support bundle action is not bound to the accepted preview contract")
    support_payload = viewmodel.split("fun supportBundlePayloadJson", 1)[1].split("fun ", 1)[0]
    require("rawJson" not in support_payload, "support bundle payload must not replay untrusted raw preview JSON")
    require('put("archive"' not in support_payload, "support bundle archive is server-managed and must not be client-injected")
    require("previewSnapshotCreate(name: String, snapshot: String)" in repository, "repository does not preview the exact reviewed snapshot name")
    snapshot_panel_signature = chroots.split("private fun SnapshotPanel", 1)[1].split(") {", 1)[0]
    require("onPreviewSnapshotCreate: (String, String) -> Unit" in snapshot_panel_signature, "SnapshotPanel preview callback is not bound to a stable snapshot name")
    require("onStartSnapshotCreate: (String, String) -> Unit" in snapshot_panel_signature, "SnapshotPanel create callback is not bound to a stable snapshot name")
    require("onRefreshStorage = refreshStorage" in app and "onRefreshLogs = refreshLogs" in app, "app callback wiring missing")

    # Tests and documentation.
    for token in (
        "phase 39 workspace exposes recovery storage logs and advanced rooms",
        "log workspace filters map only to allowlisted severity values",
        "failed chroot operation offers snapshot recovery",
        "storage formatting stays compact and deterministic",
    ):
        require(token in workflow_test, f"WorkflowUxPolicyTest missing {token}")
    require("allowlisted query `storage.status`" in doc and "allowlisted query `logs.list`" in doc, "Phase 39-40 architecture documentation incomplete")

    for key in (
        "chroot_workspace_tab_storage",
        "chroot_workspace_tab_logs",
        "snapshots_workspace_title",
        "storage_workspace_title",
        "storage_export_support_info",
        "snapshot_create_name",
        "logs_workspace_title",
        "advanced_runtime_title",
        "advanced_raw_payload_title",
        "advanced_support_title",
    ):
        require(f'name="{key}"' in strings, f"missing Phase 39-40 string resource {key}")

    # Architecture/API guardrails.
    build = read("android/app/build.gradle.kts")
    require("compileSdk = 36" in build and "targetSdk = 36" in build, "compileSdk 36 / targetSdk 36 guardrail regressed")
    manifest_and_sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (ROOT / "android/app/src/main").rglob("*")
        if p.is_file() and p.suffix in {".kt", ".xml"}
    )
    require("WebView(" not in manifest_and_sources and "android.webkit.WebView" not in manifest_and_sources, "WebView boundary regressed")
    require("HttpServer" not in manifest_and_sources and "NanoHTTPD" not in manifest_and_sources, "HTTP-server boundary regressed")
    require('check(!capabilities.arbitraryShell)' in repository, "arbitrary-shell bridge safety check regressed")
    require('"arbitraryShell": False' in dispatcher, "bridge capability declaration no longer proves arbitrary shell disabled")

    print("Phase 39-40 focused recovery/storage/logs/advanced workspace validation passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
