from __future__ import annotations
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
def test_phase27_smoke_handoff_contracts_registered() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    for token in ("smoke.last_result", "smoke.result.persist", "smoke.result.export", "smoke.failure.bundle"):
        assert token in registry
def test_phase27_smoke_handoff_ui_wired() -> None:
    combined = "\n".join(read(path) for path in (
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt",
        "android/app/src/main/res/values/strings.xml",
    ))
    for token in ("smokeLastResult", "refreshSmokeLastResult", "smokeResultPersistPayloadJson", "smoke_handoff_title"):
        assert token in combined
def test_phase27_sdk_version_and_docs() -> None:
    build = read("android/app/build.gradle.kts")
    docs = read("docs/android/PHASE_27_SMOKE_RESULT_HANDOFF.md")
    assert 'compileSdk = 36' in build
    assert 'targetSdk = 36' in build
    assert any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(27, 29))
    assert 'smoke.failure.bundle' in docs
