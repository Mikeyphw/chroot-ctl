#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

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
    bridge_cli = read("src/chrootctl/bridge/cli.py")
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    bridge_process = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    docs = read("docs/android/PHASE_34D_PROTOCOL_CAPABILITIES_PROBE.md")
    tests = read("tests/test_android_phase34d.py")

    require("compileSdk = 37" in build, "compileSdk must be API 37")
    require("targetSdk = 36" in build, "targetSdk must remain API 36")
    require("warningsAsErrors = true" in build, "strict lint warningsAsErrors must remain enabled")
    require("abortOnError = true" in build, "strict lint abortOnError must remain enabled")
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"\s*/>', lint)
    require(ignored == ["OldTargetApi"], f"only OldTargetApi may be ignored, got {ignored}")

    top_level = bridge_cli.split("def main", 1)[0]
    require("from ..services import create_service_container" not in top_level, "bridge CLI must not import the service layer at module import time")
    require("from .dispatcher import BridgeDispatcher" not in top_level, "bridge CLI must not import the dispatcher at module import time")
    require('if args.command == "capabilities"' in bridge_cli, "capabilities command must be handled explicitly")
    require(bridge_cli.find('if args.command == "capabilities"') < bridge_cli.find("from ..services import create_service_container"), "capabilities must run before service container creation")
    for token in (
        "_capabilities_response",
        "runtimeHealth",
        "CAPABILITIES_PARTIAL",
        "BridgeResponse.success(\n        \"capabilities\"",
        "operations = capabilities()",
        "Open Runtime diagnostics",
    ):
        require(token in bridge_cli, f"bridge capabilities hardening missing: {token}")

    for token in (
        'listOf("capabilities")',
        'envelope.optBoolean("ok")',
        'data.optInt("protocolVersion", -1) == BRIDGE_PROTOCOL_VERSION',
        'File(activeModuleDir, "system/bin/chrootctl")',
        'pendingModuleDirs',
        'isActiveModuleExecutable',
    ):
        require(token in resolver, f"runtime resolver guard missing: {token}")

    for token in (
        "android-stream-drain",
        "uncaughtExceptionHandler",
        "closed without crashing the root service",
    ):
        require(token in bridge_process, f"Phase 34B stream crash guard missing: {token}")

    for token in (
        "Phase 34D",
        "protocol-1 JSON envelope",
        "service-free",
        "runtimeHealth.status=degraded",
        "/data/adb/modules/chrootctl-magisk/system/bin/chrootctl",
        "API 36",
    ):
        require(token in docs, f"Phase 34D docs missing: {token}")

    for token in (
        "BlockServices",
        "services intentionally unavailable",
        'payload["ok"] is True',
        "runtimeHealth",
        "CAPABILITIES_PARTIAL",
    ):
        require(token in tests, f"Phase 34D tests missing: {token}")

    all_kotlin = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt")
    )
    for forbidden in ("WebView", "combine(arrayOf", '"/data/'):
        require(forbidden not in all_kotlin, f"forbidden Android regression returned: {forbidden}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 34D protocol capabilities probe validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
