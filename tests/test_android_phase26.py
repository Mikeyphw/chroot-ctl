from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")

def test_phase26_release_readiness_contract() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    assert "release.readiness" in registry
    assert "_release_readiness" in registry

def test_phase26_home_readiness_ui() -> None:
    combined = "\n".join(read(path) for path in (
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
        "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt",
        "android/app/src/main/res/values/strings.xml",
    ))
    for token in ("ReleaseReadinessSummary", "releaseReadiness", "ReleaseReadinessCard", "release_readiness_title"):
        assert token in combined

def test_phase26_sdk_and_smoke_continuity() -> None:
    build = read("android/app/build.gradle.kts")
    registry = read("src/chrootctl/bridge/registry.py")
    assert 'compileSdk = 36' in build
    assert 'targetSdk = 36' in build
    assert any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(26, 29))
    assert "smoke.run" in registry
