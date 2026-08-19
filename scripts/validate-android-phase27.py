#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
def err(errors: list[str], condition: bool, message: str) -> None:
    if condition: errors.append(message)
def main() -> int:
    errors: list[str] = []
    build = read("android/app/build.gradle.kts")
    registry = read("src/chrootctl/bridge/registry.py")
    repo = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    vm = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt")
    strings = read("android/app/src/main/res/values/strings.xml")
    docs = read("docs/android/PHASE_27_SMOKE_RESULT_HANDOFF.md")
    err(errors, 'compileSdk = 36' not in build, "compileSdk must be 36")
    err(errors, 'targetSdk = 36' not in build, "targetSdk must remain 36")
    err(errors, not any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(27, 30)), "versionName must advance to phase27")
    for token in ("smoke.last_result", "smoke.result.persist", "smoke.result.export", "smoke.failure.bundle", "_smoke_last_result", "_smoke_failure_bundle"):
        err(errors, token not in registry, f"registry missing smoke handoff token: {token}")
    for token in ("refreshSmokeLastResult", "smokeResultPersistPayloadJson", "smokeResultExportPayloadJson", "smokeFailureBundlePayloadJson"):
        err(errors, token not in (repo + vm), f"Android smoke handoff wiring missing: {token}")
    for token in ("onRefreshSmokeLastResult", "onPersistSmokeResult", "onExportSmokeEvidence", "onCreateSmokeFailureBundle", "smoke_last_result_action", "smokeLastResult"):
        err(errors, token not in (tools + app + strings + models), f"smoke handoff UI missing: {token}")
    for forbidden in ("WebView", "Manifest.permission.POST_NOTIFICATIONS", "combine(arrayOf", '"/data/'):
        err(errors, forbidden in (repo + vm + tools + app), f"forbidden Android token found: {forbidden}")
    for token in ("Phase 27", "smoke.last_result", "smoke.result.export", "support bundle", "SDK remains pinned to 36"):
        err(errors, token not in docs, f"phase27 docs missing token: {token}")
    if errors:
        for item in errors: print(f"ERROR: {item}")
        return 1
    print("Phase 27 smoke result handoff validator passed")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
