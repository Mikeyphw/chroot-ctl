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
    phase22 = read("scripts/validate-android-phase22.py")
    phase27 = read("scripts/validate-android-phase27.py")
    docs = read("docs/android/PHASE_28_FINAL_OPERATIONAL_RELEASE_SEAL.md")
    runbook = read("docs/android/ANDROID_RELEASE_RUNBOOK.md")
    smoke = read("docs/android/REAL_DEVICE_SMOKE_CHECKLIST.md")
    err(errors, 'compileSdk = 36' not in build, "compileSdk must remain 36")
    err(errors, 'targetSdk = 36' not in build, "targetSdk must remain 36")
    err(errors, not any(f'versionName = "0.1.0-phase{phase}"' in build for phase in (28, 29)), "versionName must advance to phase28")
    for token in ("final.preflight", "final.packaging_audit", "final.no_webui_regression", "final.release_seal", "_final_release_seal"):
        err(errors, token not in registry, f"registry missing final seal token: {token}")
    for token in ("smoke.last_result", "smoke.result.export", "smoke.failure.bundle"):
        err(errors, token not in registry or token not in phase27, f"phase28 must retain phase27 smoke handoff token: {token}")
    for token in ("FastAPI", "Jinja", "Uvicorn", "python-multipart", "chrootctl-web"):
        err(errors, token in read("pyproject.toml"), f"retired WebUI dependency/entrypoint returned: {token}")
    android_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT/"android/app/src/main/kotlin").rglob("*.kt"))
    for forbidden in ("WebView", "Manifest.permission.POST_NOTIFICATIONS", "combine(arrayOf", '"/data/'):
        err(errors, forbidden in android_text, f"forbidden Android token found: {forbidden}")
    for token in ("Phase 28", "final.release_seal", "SDK remains pinned to 36"):
        err(errors, token not in docs, f"phase28 docs missing token: {token}")
    for token in ("Run the real-device smoke suite", "WebUI remains retired"):
        err(errors, token not in runbook, f"runbook missing token: {token}")
    for token in ("Last smoke result", "Smoke evidence"):
        err(errors, token not in smoke, f"smoke checklist missing token: {token}")
    err(errors, "range(22, 30)" not in phase22, "phase22 validator must accept phase28 release-hardening versions")
    if errors:
        for item in errors: print(f"ERROR: {item}")
        return 1
    print("Phase 28 final operational release seal validator passed")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
