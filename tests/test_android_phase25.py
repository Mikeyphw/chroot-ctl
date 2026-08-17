from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")

def test_phase25_smoke_contracts_registered() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    for token in ("smoke.plan", "smoke.run", "smoke.report"):
        assert token in registry

def test_phase25_android_smoke_ui_wired() -> None:
    combined = "\n".join(read(path) for path in (
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
        "android/app/src/main/res/values/strings.xml",
    ))
    for token in ("previewSmokePlan", "smokeRunPayloadJson", "refreshSmokeReport", "smoke_suite_title"):
        assert token in combined

def test_phase25_sdk_and_docs() -> None:
    build = read("android/app/build.gradle.kts")
    docs = read("docs/android/PHASE_25_REAL_DEVICE_OPERATIONAL_SMOKE.md")
    assert 'compileSdk = 37' in build
    assert 'targetSdk = 36' in build
    assert any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(25, 30))
    assert 'smoke.run' in docs
