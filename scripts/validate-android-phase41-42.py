#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def main() -> int:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    cards = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AppCards.kt")
    adaptive = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/AdaptiveLayoutPolicy.kt")
    navigation = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AdaptiveNavigationShell.kt")
    view_model = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    release = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicy.kt")
    tokens = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/UiTokens.kt")
    registry = read("src/chrootctl/bridge/registry.py")
    strings = read("android/app/src/main/res/values/strings.xml")
    workflow_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicyTest.kt")
    release_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicyTest.kt")
    doc = read("docs/android/PHASE_41_42_UI_QUALITY_REAL_DEVICE_SMOKE.md")
    checklist = read("docs/android/REAL_DEVICE_SMOKE_CHECKLIST.md")

    # Adaptive layout / accessibility.
    require("BoxWithConstraints(modifier.fillMaxWidth())" in cards, "shared section header is not width-adaptive")
    require("sectionHeaderStacks(maxWidth.value, LocalDensity.current.fontScale)" in cards, "shared header is not using the tested adaptive policy")
    require("fun sectionHeaderStacks" in adaptive and "LARGE_TYPE_LAYOUT_THRESHOLD" in adaptive, "adaptive large-type header policy missing")
    require("compactNavigationShowsVisualLabels" in navigation and "alwaysShowLabel = showCompactVisualLabels" in navigation, "compact navigation is not hardened for large font scale")
    require(".focusGroup()" in cards, "action rows are not keyboard/switch focus groups")
    require("SupportedFontScalePercent: Int = 200" in tokens, "200% font-scale contract regressed")
    require("MinimumTouchTargetDp: Int = 48" in tokens, "48dp touch-target contract regressed")
    require("pane-title-per-workspace-room" in release and "keyboard-traversal-groups" in release, "release accessibility seal incomplete")
    require("paneTitle = paneDescription" in source, "selected workspace pane title missing")
    for token in ("snapshots_workspace_title", "storage_workspace_title", "logs_workspace_title", "users_workspace_title", "services_workspace_title"):
        require(f"paneTitleText = stringResource(R.string.{token})" in source, f"pane title missing for {token}")
    require("paneTitle = reviewTitle" in source, "mutation review pane titles missing")

    # Restoration policy: safe state saveable; mutation review/confirmation state transient.
    require("object WorkspaceRestorationPolicy" in policy, "workspace restoration policy missing")
    for key in ("workspace-tab", "services-filter", "users-filter", "logs-filter", "logs-live-tail"):
        require(f'"{key}"' in policy, f"safe restoration key missing: {key}")
    for key in ("snapshot-review", "snapshot-restore-confirmation", "user-review", "service-review", "remove-confirmation"):
        require(f'"{key}"' in policy, f"transient mutation key missing: {key}")
    require('var reviewToken by remember(chroot.name)' in source, "snapshot review is still saveable")
    require('var restoreConfirmation by remember(chroot.name, action.name, snapshot?.name)' in source, "restore confirmation is still saveable")
    require('val createSnapshotName by remember(chroot.name, action.name, snapshot?.name)' in source, "snapshot create identity is still saveable")
    require('var reviewUserToken by remember(chroot.name)' in source, "user review is still saveable")
    require('var pendingActionToken by remember(chroot.name)' in source, "service review is still saveable")
    for forbidden in (
        'var reviewToken by rememberSaveable',
        'var restoreConfirmation by rememberSaveable',
        'val createSnapshotName by rememberSaveable',
        'var reviewUserToken by rememberSaveable',
        'var pendingActionToken by rememberSaveable',
    ):
        require(forbidden not in source, f"dangerous state restoration regression: {forbidden}")

    # Explicit pane states.
    for token in ("Loading", "Empty", "Ready", "Failure"):
        require(token in policy.split("enum class WorkspacePaneState", 1)[1].split("}", 1)[0], f"WorkspacePaneState missing {token}")
    room_functions = (
        "AdvancedWorkspaceTab",
        "SnapshotPanel",
        "StoragePanel",
        "LogsPanel",
        "UsersPanel",
        "ServicesPanel",
    )
    for index, room in enumerate(room_functions):
        marker = f"private fun {room}("
        require(marker in source, f"workspace room missing: {room}")
        start = source.index(marker)
        following = [source.find(f"private fun {other}(", start + len(marker)) for other in room_functions[index + 1 :]]
        following = [position for position in following if position >= 0]
        end = min(following) if following else len(source)
        segment = source[start:end]
        require("workspacePaneState(" in segment, f"{room} does not derive explicit loading/empty/ready/failure state")
        require("WorkspacePaneFeedback(" in segment, f"{room} does not render shared pane-state feedback/retry UI")
    for key in ("workspace_loading_services", "workspace_loading_users", "workspace_loading_snapshots", "workspace_loading_storage", "workspace_loading_logs", "workspace_loading_advanced"):
        require(f'name="{key}"' in strings, f"missing loading string {key}")
    require("WorkspacePaneState.Failure" in source, "retryable workspace failure feedback missing")
    require(source.count("paneTitle = reviewTitle") >= 3, "snapshot/user/service mutation reviews do not all expose pane titles")

    # Logs lifecycle hardening. Keep the Phase 40 effect keys while lifecycle gates collection.
    require("LocalLifecycleOwner.current" in source, "Logs does not observe Android lifecycle")
    require("repeatOnLifecycle(Lifecycle.State.STARTED)" in source, "Logs lifecycle STARTED gate missing")
    require("while (liveTail)" in source, "Logs polling loop missing")
    require("LaunchedEffect(liveTail, filterName, chroot.name)" in source, "Phase 40 live-tail effect shape changed")

    # Degraded protocol behavior.
    for op in ("services.list", "users.list", "snapshots.list", "storage.status", "logs.list"):
        require(f'"{op}"' in policy, f"workspace capability requirement missing: {op}")
    require("workspaceTabSupported(tab, availableOperations)" in source, "workspace tabs are not capability-aware")
    require("availableOperations?.contains(required) == true" in policy, "unknown capabilities still enable gated workspace rooms")
    require("workspaceSelectionNeedsRebind" in source and "requestedWorkspaceSelection" in source, "restored workspace does not re-bind backend selection")
    require("availableWorkspaceOperations" in view_model and "refreshCapabilityGatedChrootRooms" in view_model, "ViewModel still fires capability-gated room queries while capabilities are unknown")
    require("workspaceTabSupported(ChrootWorkspaceTab.Users, operations)" in view_model, "Users refresh is not capability gated")
    require("workspaceTabSupported(ChrootWorkspaceTab.Services, operations)" in view_model, "Services refresh is not capability gated")
    require("enabled = supported" in source, "unsupported workspace tabs are not disabled")
    require("effectiveWorkspaceTab(selectedTab, availableOperations)" in source, "unsupported/unknown restored tab does not fall back safely")
    require("shouldPersistWorkspaceFallback(selectedTab, effectiveTab, capabilitiesKnown)" in source, "temporary unknown-capability fallback incorrectly overwrites saved tab state")
    require("fun shouldPersistWorkspaceFallback" in policy, "workspace fallback persistence policy missing")
    require("chroot_workspace_degraded_title" in source, "degraded capability notice missing")
    require("degraded protocol disables only rooms whose query capability is missing" in workflow_test, "degraded-protocol Kotlin contract test missing")

    # Real-device smoke plan.
    for step in (
        "root_module_discovery",
        "workspace_services",
        "workspace_users",
        "workspace_snapshots",
        "workspace_storage",
        "workspace_logs",
        "workspace_advanced",
        "degraded_protocol_fallback",
        "root_service_reconnect",
    ):
        require(f'"{step}"' in registry, f"smoke plan missing {step}")
    require('_module_status(services, {})' in registry, "root-module smoke step is not executable")
    require('step.get("kind") == "manual"' in registry, "manual Android recovery smoke steps are not preserved")
    require("phase 42 real device smoke seal covers every selected chroot room" in release_test, "Phase 42 release contract test missing")
    for phrase in ("200% font scale", "RootService reconnect", "degraded", "Services", "Users", "Snapshots", "Storage", "Logs", "Advanced"):
        require(phrase in checklist, f"real-device smoke checklist missing {phrase}")
    require("mutation review state is deliberately transient" in doc.lower(), "Phase 41-42 restoration architecture documentation missing")

    # Resource parse.
    ET.parse(ROOT / "android/app/src/main/res/values/strings.xml")

    # Architecture/API and protected-runtime guardrails.
    build = read("android/app/build.gradle.kts")
    require("compileSdk = 36" in build and "targetSdk = 36" in build, "API 36 guardrail regressed")
    protected_hashes = {
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt": "1119ce7d635dc71531934838b1370864c8c856313e13a67d2704f69f427856bb",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt": "603695276da2e054b0067626541feca2d5ee1507c448952665b7ac05202f57a4",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt": "846acef5e80773eebc06acdb376781ca54220b3964240a2d176cd4fc66724ad0",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt": "6c97ed75b1a24c6b52f73ff2394966395a57b8c7a907c7a5235bb15298de4188",
        "android/app/lint.xml": "dae3a0a90ef1a7a1a05fc8a2f2043b589a0fc274611911bf2f5daed3063ae86f",
    }
    for rel, expected in protected_hashes.items():
        require(sha(rel) == expected, f"protected landed runtime file changed: {rel}")
    main_sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (ROOT / "android/app/src/main").rglob("*")
        if p.is_file() and p.suffix in {".kt", ".xml"}
    )
    require("android.webkit.WebView" not in main_sources and "WebView(" not in main_sources, "WebView boundary regressed")
    require("NanoHTTPD" not in main_sources and "HttpServer" not in main_sources, "HTTP-server boundary regressed")
    require('check(!capabilities.arbitraryShell)' in read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt"), "arbitrary-shell safety check regressed")

    print("Phase 41-42 UI quality and real-device smoke seal validation passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
