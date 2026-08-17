from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_activity_recovery_center_has_filters_and_manual_recovery_actions() -> None:
    activity = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/activity/ActivityScreen.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ActivityRecoveryPolicy.kt")
    assert "OperationActivityFilter" in activity
    assert "FilterChip" in activity
    assert "onCancelOperation" in activity
    assert "onRetryOperation" in activity
    assert "onRetryWithFixes" in activity
    assert "onRecoverLatestSnapshot" in activity
    assert "AlertDialog" in activity
    strings = read("android/app/src/main/res/values/strings.xml")
    assert "redacted secrets" in strings
    assert "previewRetryOperation" in activity
    assert "previewRetryWithFixes" in activity
    assert "operation_retry_fixes_preview_action" in activity
    assert "canRetryWithFixes" in policy
    assert "install.run" in policy


def test_tools_are_focused_workspaces_with_logs_repair_and_help() -> None:
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ToolsWorkspacePolicy.kt")
    for token in ["Catalog", "Packages", "Transfer", "Runtime", "Logs", "Repair", "Help"]:
        assert token in policy
    assert "WorkspaceSelector" in tools
    assert "LogsWorkspaceCard" in tools
    assert "LaunchedEffect" in tools and "delay(3_000L)" in tools
    assert "RepairWorkspaceCard" in tools
    assert "selectedRepairItemIds" in tools
    assert "HelpAndApiCard" in tools
    assert "ToolGroupCard(group)" in tools


def test_selective_repair_payload_replaces_apply_all() -> None:
    vm = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt")
    assert "RepairItemSummary" in models
    assert "selectedRepairItemIds" in models
    assert "toggleRepairItem" in vm
    assert "repairDecisionsJson" in vm
    assert "put(\"decisions\"" in vm
    assert "applyAll" not in vm


def test_retry_operation_bridge_is_redaction_checked() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    vm = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    assert 'OperationSpec("operations.retry"' in registry
    assert "_contains_redacted" in registry
    assert "REDACTED_RETRY_REQUEST" in registry
    assert "INVALID_RETRY_MODE" in registry
    assert "REPAIR_DECISIONS_REQUIRED" in registry
    assert 'original_operation != "install.run"' in registry
    assert 'original_payload["repair"] = True' in registry
    assert 'original_payload["resume"] = True' in registry
    assert 'onStartBridgeOperation("operations.retry"' in app
    assert "viewModel.refreshSnapshots(target)" in app
    assert "retryOperationPayloadJson" in vm


def test_phase33_preserves_native_boundaries() -> None:
    kotlin = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"))
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    assert "WebView" not in kotlin
    assert "http://" not in kotlin and "https://" not in kotlin
    assert "targetSdk = 36" in build
    assert "compileSdk = 37" in build
    assert 'id="OldTargetApi"' in lint
    assert "GradleDependency" not in lint
    assert "NewerVersionAvailable" not in lint
