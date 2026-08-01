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
    models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt")
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    strings = read("android/app/src/main/res/values/strings.xml")
    docs = read("docs/android/PHASE_26_UX_RELEASE_READINESS.md")

    err(errors, 'compileSdk = 36' not in build, "compileSdk must remain 36")
    err(errors, 'targetSdk = 36' not in build, "targetSdk must remain 36")
    err(errors, not any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(26, 29)), "versionName must advance to phase26")
    for token in ("release.readiness", "_release_readiness", "smoke.run"):
        err(errors, token not in registry, f"registry missing release-readiness token: {token}")
    for token in ("ReleaseReadinessSummary", "releaseReadiness", "toReleaseReadinessSummary"):
        err(errors, token not in (models + repo), f"release readiness state wiring missing: {token}")
    for token in ("ReleaseReadinessCard", "release_readiness_title"):
        err(errors, token not in (home + strings), f"Home release readiness UI missing: {token}")
    for forbidden in ("WebView", "Manifest.permission.POST_NOTIFICATIONS", "combine(arrayOf", '"/data/'):
        err(errors, forbidden in (repo + home), f"forbidden Android token found: {forbidden}")
    for token in ("Phase 26", "release.readiness", "Home shows a Release readiness card", "SDK remains pinned to 36"):
        err(errors, token not in docs, f"phase26 docs missing token: {token}")
    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("Phase 26 UX release readiness validator passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
