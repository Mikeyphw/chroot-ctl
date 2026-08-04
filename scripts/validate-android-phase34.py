#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    adaptive = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/AdaptiveLayoutPolicy.kt")
    tokens = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/UiTokens.kt")
    release = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicy.kt")
    shell = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AdaptiveNavigationShell.kt")
    cards = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AppCards.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    activity = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/activity/ActivityScreen.kt")
    registry = read("src/chrootctl/bridge/registry.py")

    require("compileSdk = 36" in build and "targetSdk = 36" in build, "Phase 34 must preserve SDK 36")
    require(re.findall(r'id="([^"]+)"', lint) == ["OldTargetApi"], "lint.xml must ignore only OldTargetApi")
    for token in ["PhonePortrait", "PhoneLandscape", "Foldable", "Tablet", "DesktopWidth", "releaseWindowProfile"]:
        require(token in adaptive, f"adaptive release profile missing: {token}")
    for token in ["MinimumTouchTargetDp", "SupportedFontScalePercent", "LiveLogPollingSeconds", "SmokeProfileCount"]:
        require(token in tokens, f"release accessibility token missing: {token}")
    for token in ["minimumTouchTargetDp", "supportedFontScalePercent", "smokeProfiles", "accessibilitySealChecks", "validatesReleaseContract"]:
        require(token in release, f"release UX policy missing: {token}")
    require("paneTitle" in app and "currentPaneTitle" in app, "destination pane title semantics missing")
    require("heightIn(min = ChrootLayout.MinimumTouchTarget)" in shell, "navigation minimum touch target missing")
    require("releaseTouchTarget" in cards and "heightIn(min = ChrootLayout.MinimumTouchTarget)" in cards, "action flow touch target policy missing")
    require("delay(3_000L)" in tools, "bounded three-second log polling must be preserved")
    require("applyAll" not in tools + app, "Android repair UI must not use applyAll")
    require("REDACTED_RETRY_REQUEST" in registry and "_contains_redacted" in registry, "retry redaction guard must be preserved")
    native_sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt") if ".bak" not in path.name)
    require("WebView" not in native_sources, "Phase 34 must not reintroduce WebView")
    require("http://" not in native_sources and "https://" not in native_sources, "Phase 34 must not add HTTP endpoints")
    require("AlertDialog" in activity and "onRetryWithFixes" in activity, "Activity recovery center must survive release seal")
    require("operation_retry_fixes_preview_action" in activity, "retry-with-fixes must be preview-first in the UI")
    require("viewModel.refreshSnapshots(target)" in app, "snapshot recovery handoff must refresh snapshots")
    require("REPAIR_DECISIONS_REQUIRED" in registry, "repair.apply must reject missing explicit decisions")
    require(activity.count("heightIn(min = ChrootLayout.MinimumTouchTarget)") >= 5, "Activity actions must have explicit 48dp targets")
    require(tools.count("heightIn(min = ChrootLayout.MinimumTouchTarget)") >= 20, "Tools workspace actions must have explicit 48dp targets")
    ET.parse(ROOT / "android/app/src/main/res/values/strings.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
