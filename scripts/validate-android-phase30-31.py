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
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    destination = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/AppDestination.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/AdaptiveLayoutPolicy.kt")
    tokens = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/UiTokens.kt")
    messages = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/UiMessagePolicy.kt")
    shell = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AdaptiveNavigationShell.kt")
    cards = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AppCards.kt")
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    theme = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/Theme.kt")
    tests = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/UiFoundationPolicyTest.kt")
    strings_path = ROOT / "android/app/src/main/res/values/strings.xml"
    strings = read("android/app/src/main/res/values/strings.xml")

    require("compileSdk = 37" in build and "targetSdk = 36" in build, "compileSdk 37 / targetSdk 36 contract changed")
    require("warningsAsErrors = true" in build and "abortOnError = true" in build, "strict lint policy changed")
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"', lint)
    require(ignored == ["OldTargetApi"], f"unexpected ignored lint issues: {ignored}")

    require("COMPACT_NAVIGATION_BREAKPOINT_DP: Float = 720f" in policy, "720 dp navigation breakpoint missing")
    require("PrimaryNavigationType.BottomBar" in policy and "PrimaryNavigationType.Rail" in policy, "adaptive navigation policy incomplete")
    require("MaximumContentWidth: Dp = 1180.dp" in tokens, "maximum content width missing")
    require("MinimumTouchTarget: Dp = 48.dp" in tokens, "48 dp touch-target token missing")
    require("NavigationRailWidth: Dp = 92.dp" in tokens, "navigation rail width token missing")

    for token in ("AdaptiveNavigationShell", "NavigationBar", "NavigationRail", "safeDrawingPadding", "primaryDestinations"):
        require(token in shell, f"adaptive shell missing {token}")
    for item in ("Home", "Chroots", "Install", "Activity", "Tools"):
        require(f"    {item}(" in destination, f"primary navigation enum missing {item}")
    require("private val primaryDestinations: List<AppDestination> = AppDestination.entries.toList()" in shell, "primary navigation must enumerate the stable destination enum")
    require("Help(" not in destination, "Help must not become a primary destination")
    require("rememberSaveable" in app, "destination state is not saved")
    require("widthIn(max = ChrootLayout.MaximumContentWidth)" in app, "content max-width policy is not applied")
    require("PageHeader(" in app, "shared page header is not used")

    for token in ("ActionFlowRow", "StatusPill", "SectionHeader", "PageHeader", "DashboardLoadingState", "RecoverableErrorState", "RefreshFailureBanner", "ResponsiveMetricCards"):
        require(token in cards, f"shared UI component missing: {token}")
    require("FlowRow(" in cards and "heightIn(min = ChrootLayout.MinimumTouchTarget)" in cards, "responsive action/touch policy missing")

    for token in ("DashboardOverview", "HomeHero", "SystemHealthCard", "RecentActivityCard", "ResponsiveMetricCards", "InitialBackendFailure", "RefreshFailureBanner"):
        require(token in home, f"Home dashboard missing {token}")
    require("onOpenChroots" in home and "onOpenInstall" in home and "onOpenActivity" in home, "Home quick routes are incomplete")
    require("chroots.count { isRunningChrootStatus" in home, "running chroot metric missing")
    require("operations.count { isRunningOperationState" in home, "running operation metric missing")
    require("technicalDetails = message" in home and "technicalDetails = refreshState.message" in home, "technical details are not preserved")
    require("DeadObjectException" not in strings, "raw Binder exception leaked into user-facing strings")

    for token in ("ServiceDisconnected", "Timeout", "InvalidResponse", "PermissionDenied", "RuntimeMissing"):
        require(token in messages, f"backend error classification missing {token}")
    require('"deadobjectexception" in message' in messages, "Binder death classification missing")
    require('"json" in message' in messages, "invalid response classification missing")

    require("Color(0xFFB8FF69)" in theme and "Color(0xFF0F1113)" in theme, "new visual identity is incomplete")
    require("RoundedCornerShape(28.dp)" in theme, "large shape token missing")

    for token in ("compact width uses bottom navigation", "expanded width uses navigation rail", "binder death is classified", "running state helpers"):
        require(token in tests, f"policy unit test missing: {token}")

    parsed = ET.parse(strings_path)
    string_names = {node.attrib["name"] for node in parsed.getroot() if node.tag == "string"}
    references: set[str] = set()
    for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"):
        references.update(re.findall(r"R\.string\.([A-Za-z0-9_]+)", path.read_text(encoding="utf-8")))
    missing = sorted(references - string_names)
    require(not missing, f"missing string resources: {missing}")

    kotlin = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"))
    require("WebView" not in kotlin, "WebView trust boundary introduced")
    require("Runtime.getRuntime().exec" not in kotlin, "arbitrary process execution introduced")
    require("http://" not in kotlin and "https://" not in kotlin, "HTTP surface introduced")

    for old in ("scripts/validate-android-phase29.py", "scripts/validate-android-phase29c.py", "scripts/validate-android-phase29d.py", "scripts/validate-android-phase29f.py"):
        require((ROOT / old).is_file(), f"prior validator missing: {old}")

    print("Phase 30–31 UI foundation and Home dashboard validation passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
