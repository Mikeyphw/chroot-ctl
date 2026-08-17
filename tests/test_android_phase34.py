from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase34_adaptive_release_profiles_are_explicit() -> None:
    adaptive = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/AdaptiveLayoutPolicy.kt")
    release = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicy.kt")
    for token in ["PhonePortrait", "PhoneLandscape", "Foldable", "Tablet", "DesktopWidth"]:
        assert token in adaptive
        assert token.lower().replace("phone", "phone-") or token in release
    assert "releaseWindowProfile" in adaptive
    assert "smokeProfiles" in release
    assert "font-scale-200-percent" in release
    assert "no-automatic-mutating-replay" in release


def test_phase34_accessibility_touch_and_pane_titles_are_enforced() -> None:
    shell = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AdaptiveNavigationShell.kt")
    cards = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AppCards.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    tokens = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/UiTokens.kt")
    assert "MinimumTouchTargetDp: Int = 48" in tokens
    assert "SupportedFontScalePercent: Int = 200" in tokens
    assert "heightIn(min = ChrootLayout.MinimumTouchTarget)" in shell
    assert "contentDescription = label" in shell
    assert "releaseTouchTarget" in cards
    assert "paneTitle = currentPaneTitle" in app
    assert "viewModel.refreshSnapshots(target)" in app


def test_phase34_release_seal_preserves_security_and_lint_boundaries() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    registry = read("src/chrootctl/bridge/registry.py")
    kotlin = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt") if ".bak" not in path.name)
    assert "compileSdk = 37" in build
    assert "targetSdk = 36" in build
    assert re.findall(r'id="([^"]+)"', lint) == ["OldTargetApi"]
    assert "WebView" not in kotlin
    assert "http://" not in kotlin and "https://" not in kotlin
    assert "REDACTED_RETRY_REQUEST" in registry
    assert "_contains_redacted" in registry
    assert "applyAll" not in read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    assert "REPAIR_DECISIONS_REQUIRED" in registry
    assert "INVALID_RETRY_MODE" in registry


def test_phase34_merged_overlay_keeps_phase33_workspaces() -> None:
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    activity = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/activity/ActivityScreen.kt")
    assert "WorkspaceSelector" in tools
    assert "LogsWorkspaceCard" in tools
    assert "RepairWorkspaceCard" in tools
    assert "HelpAndApiCard" in tools
    assert "delay(3_000L)" in tools
    assert "OperationActivityFilter" in activity
    assert "onRetryWithFixes" in activity
    assert "operation_retry_fixes_preview_action" in activity
    assert activity.count("heightIn(min = ChrootLayout.MinimumTouchTarget)") >= 5
    assert tools.count("heightIn(min = ChrootLayout.MinimumTouchTarget)") >= 20
    assert "onRecoverLatestSnapshot" in activity
