from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase41_42_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate-android-phase41-42.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_device_smoke_plan_covers_every_workspace_and_recovery_hinge() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from chrootctl.bridge.registry import _smoke_steps

        steps = {step["id"]: step for step in _smoke_steps("demo")}
    finally:
        sys.path.pop(0)

    required = {
        "root_module_discovery",
        "workspace_services",
        "workspace_users",
        "workspace_snapshots",
        "workspace_storage",
        "workspace_logs",
        "workspace_advanced",
        "degraded_protocol_fallback",
        "root_service_reconnect",
    }
    assert required <= steps.keys()
    assert steps["workspace_services"]["operation"] == "services.list"
    assert steps["workspace_users"]["operation"] == "users.list"
    assert steps["workspace_snapshots"]["operation"] == "snapshots.list"
    assert steps["workspace_storage"]["operation"] == "storage.status"
    assert steps["workspace_logs"]["operation"] == "logs.list"
    assert steps["workspace_advanced"]["operation"] == "system.runtime"
    for step_id in ("workspace_services", "workspace_users", "workspace_snapshots", "workspace_storage", "workspace_logs", "workspace_advanced"):
        assert steps[step_id]["required"] is True
    no_target = {step["id"]: step for step in _smoke_steps(None)}
    for step_id in ("workspace_services", "workspace_users", "workspace_snapshots", "workspace_storage", "workspace_logs"):
        assert no_target[step_id]["required"] is False
    assert no_target["workspace_advanced"]["required"] is True
    assert steps["degraded_protocol_fallback"]["kind"] == "manual"
    assert steps["root_service_reconnect"]["kind"] == "manual"


def test_mutation_review_state_is_transient_but_safe_navigation_is_saveable() -> None:
    source = (ROOT / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt").read_text()

    transient_markers = [
        'var reviewToken by remember(chroot.name) { mutableStateOf("") }',
        'var restoreConfirmation by remember(chroot.name, action.name, snapshot?.name) { mutableStateOf("") }',
        'val createSnapshotName by remember(chroot.name, action.name, snapshot?.name)',
        'var reviewUserToken by remember(chroot.name) { mutableStateOf("") }',
        'var pendingActionToken by remember(chroot.name) { mutableStateOf("") }',
    ]
    for marker in transient_markers:
        assert marker in source

    assert "var workspaceTabName by rememberSaveable" in source
    assert 'mutableStateOf(ServiceWorkspaceFilter.All.name)' in source
    assert 'mutableStateOf(UserWorkspaceFilter.Managed.name)' in source
    assert 'mutableStateOf(LogWorkspaceFilter.All.name)' in source
    assert "var liveTail by rememberSaveable" in source


def test_logs_live_tail_is_lifecycle_aware_and_degraded_protocol_is_capability_gated() -> None:
    source = (ROOT / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt").read_text()
    policy = (ROOT / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt").read_text()
    view_model = (ROOT / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt").read_text()

    assert "Lifecycle.State.STARTED" in source
    assert "repeatOnLifecycle(Lifecycle.State.STARTED)" in source
    assert "LaunchedEffect(liveTail, filterName, chroot.name)" in source
    assert "while (liveTail)" in source
    assert "workspaceTabSupported" in source
    assert 'Storage -> "storage.status"' in policy
    assert 'Logs -> "logs.list"' in policy
    assert "availableOperations?.contains(required) == true" in policy
    assert "workspaceSelectionNeedsRebind" in source
    assert "requestedWorkspaceSelection" in source
    assert "effectiveWorkspaceTab(selectedTab, availableOperations)" in source
    assert "shouldPersistWorkspaceFallback(selectedTab, effectiveTab, capabilitiesKnown)" in source
    assert "availableWorkspaceOperations" in view_model
    assert "refreshCapabilityGatedChrootRooms" in view_model
    assert "workspaceTabSupported(ChrootWorkspaceTab.Users, operations)" in view_model
    assert "workspaceTabSupported(ChrootWorkspaceTab.Services, operations)" in view_model


def test_smoke_run_reports_manual_pending_and_target_workspace_failures_are_blocking() -> None:
    registry = (ROOT / "src/chrootctl/bridge/registry.py").read_text()
    assert "workspace_required = bool(target_name)" in registry
    assert '"required": workspace_required' in registry
    assert '"id": "workspace_advanced"' in registry and '"required": True' in registry
    assert '"manualPendingCount": len(manual_pending)' in registry
    assert '"Manual Android smoke checks remain pending."' in registry


def test_smoke_result_truthfulness_tracks_failure_and_manual_debt() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from chrootctl.bridge.registry import _smoke_result_failed, _smoke_result_manual_pending
    finally:
        sys.path.pop(0)

    clean = {"state": "succeeded", "resultPayload": {"ok": True, "failCount": 0, "blocking": [], "manualPendingCount": 2}}
    failed = {"state": "succeeded", "resultPayload": {"ok": False, "failCount": 1, "blocking": [{"code": "workspace_logs"}]}}
    assert _smoke_result_failed(clean) is False
    assert _smoke_result_manual_pending(clean) == 2
    assert _smoke_result_failed(failed) is True
    assert _smoke_result_manual_pending(failed) == 0

    registry = (ROOT / "src/chrootctl/bridge/registry.py").read_text()
    assert '"ok": latest is not None and not failed' in registry
    assert '"code": "smoke_failed"' in registry
    assert '"status": "fail" if smoke.get("failed")' in registry


def test_validator_checks_each_workspace_state_surface_individually() -> None:
    validator = (ROOT / "scripts/validate-android-phase41-42.py").read_text()
    for room in ("AdvancedWorkspaceTab", "SnapshotPanel", "StoragePanel", "LogsPanel", "UsersPanel", "ServicesPanel"):
        assert f'"{room}"' in validator
    assert 'require("workspacePaneState(" in segment' in validator
    assert 'require("WorkspacePaneFeedback(" in segment' in validator
    assert 'source.count("paneTitle = reviewTitle") >= 3' in validator
