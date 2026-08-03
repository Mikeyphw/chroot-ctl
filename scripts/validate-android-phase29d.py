#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def main() -> int:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    bridge_models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModels.kt")
    bridge_process = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    bridge_validator = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeOutputValidator.kt")
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    root_service = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt")
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    install = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/install/InstallScreen.kt")
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    docs = read("docs/android/PHASE_29D_RUNTIME_BOOTSTRAP_AND_RESPONSIVE_ACTIONS.md")

    require("compileSdk = 36" in build, "compileSdk must remain 36")
    require("targetSdk = 36" in build, "targetSdk must remain 36")
    require("warningsAsErrors = true" in build, "warningsAsErrors must remain enabled")
    require('<issue id="OldTargetApi" severity="ignore" />' in lint, "Phase 29C OldTargetApi policy must remain")

    for token in (
        'File(termuxHome, ".local/bin/chrootctl")',
        "selectCompatibleRuntime",
        'listOf("capabilities")',
        "data.optInt(\"protocolVersion\", -1) == BRIDGE_PROTOCOL_VERSION",
        "RuntimeResolver.invalidate(runtime)",
    ):
        require(token in resolver + root_service, f"runtime compatibility guard missing: {token}")

    require("redirectErrorStream(true)" not in bridge_process, "stderr must not be merged into JSON stdout")
    for token in ("errorOutput", "chrootctl-bridge-stdout", "chrootctl-bridge-stderr"):
        require(token in bridge_process, f"bridge stream capture missing: {token}")

    for token in (
        "INVALID_BRIDGE_RESPONSE",
        "EMPTY_BRIDGE_RESPONSE",
        "UNSUPPORTED_BRIDGE_PROTOCOL",
        "bridgeOutputExcerpt",
    ):
        require(token in bridge_validator, f"bridge output validator missing: {token}")

    require("operationsJson.getJSONObject" not in bridge_models, "legacy string capabilities must not use getJSONObject")
    require("is String -> add(" in bridge_models, "legacy string capability fallback missing")
    require("expected a JSON object" in bridge_models, "object shape error must be explicit")
    require("expected a JSON array" in bridge_models, "array shape error must be explicit")
    require("return data ?: JSONObject()" not in bridge_models, "wrong object shape must not become an empty object")
    require("return dataArray ?: JSONArray()" not in bridge_models, "wrong array shape must not become an empty array")

    require("Loadable.Loading -> when (refreshState)" in home, "Home loading state must react to refresh failure")
    require("is RefreshState.Failed -> StatusCard" in home, "Home initial failure card missing")
    require("action_retry" in home, "Home initial failure Retry action missing")

    require("FlowRow(" in home, "Home action wrapping missing")
    require("FlowRow(" in install, "Install action wrapping missing")
    require(tools.count("FlowRow(") >= 10, "Tools action groups are not comprehensively wrapping")
    require("smoke_export_action" in tools and "smoke_report_action" in tools, "smoke actions must remain wired")

    for token in (
        "Phase 29D",
        "protocol-1",
        "Checking root and chrootctl runtime",
        "FlowRow",
        "compileSdk = 36",
        "targetSdk = 36",
    ):
        require(token in docs, f"Phase 29D docs missing: {token}")

    kotlin = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt")
    )
    for forbidden in ("WebView", "combine(arrayOf", '"/data/'):
        require(forbidden not in kotlin, f"forbidden Android regression returned: {forbidden}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 29D runtime bootstrap and responsive actions validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
