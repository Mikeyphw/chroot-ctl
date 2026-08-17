#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")

def err(errors: list[str], condition: bool, message: str) -> None:
    if condition:
        errors.append(message)

def main() -> int:
    errors: list[str] = []
    build = read("android/app/build.gradle.kts")
    registry = read("src/chrootctl/bridge/registry.py")
    repo = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    vm = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    strings = read("android/app/src/main/res/values/strings.xml")
    docs = read("docs/android/PHASE_25_REAL_DEVICE_OPERATIONAL_SMOKE.md")

    err(errors, 'compileSdk = 37' not in build, "compileSdk must be 37")
    err(errors, 'targetSdk = 36' not in build, "targetSdk must remain 36")
    err(errors, not any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(25, 30)), "versionName must advance to phase25")
    for token in ("smoke.plan", "smoke.run", "smoke.report", "_smoke_plan", "_smoke_run", "_smoke_report"):
        err(errors, token not in registry, f"registry missing smoke token: {token}")
    for token in ("previewSmokePlan", "refreshSmokeReport"):
        err(errors, token not in repo or token not in vm, f"Android smoke bridge wiring missing: {token}")
    for token in ("smokeRunPayloadJson", "onStartSmokeRun", "smoke_suite_title", "smoke_report_action"):
        err(errors, token not in (vm + tools + strings), f"smoke UI token missing: {token}")
    for forbidden in ("WebView", "Manifest.permission.POST_NOTIFICATIONS", "combine(arrayOf", '"/data/'):
        err(errors, forbidden in (repo + vm + tools), f"forbidden Android token found: {forbidden}")
    for token in ("Phase 25", "Real-device operational smoke", "smoke.plan", "smoke.run", "SDK remains pinned to 36"):
        err(errors, token not in docs, f"phase25 docs missing token: {token}")
    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("Phase 25 real-device smoke validator passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
