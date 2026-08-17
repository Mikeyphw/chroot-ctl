from __future__ import annotations
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
def test_phase28_final_bridge_contracts_registered() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    for token in ("final.preflight", "final.packaging_audit", "final.no_webui_regression", "final.release_seal"):
        assert token in registry
def test_phase28_webui_still_retired_and_sdk_pinned() -> None:
    pyproject = read("pyproject.toml")
    build = read("android/app/build.gradle.kts")
    for token in ("FastAPI", "Jinja2", "Uvicorn", "python-multipart", "chrootctl-web"):
        assert token not in pyproject
    assert 'compileSdk = 37' in build
    assert 'targetSdk = 36' in build
    assert any(f'versionName = "0.1.0-phase{phase}"' in build for phase in (28, 29))
def test_phase28_release_docs_present() -> None:
    assert 'final.release_seal' in read("docs/android/PHASE_28_FINAL_OPERATIONAL_RELEASE_SEAL.md")
    assert 'Run the real-device smoke suite' in read("docs/android/ANDROID_RELEASE_RUNBOOK.md")
    assert 'Smoke evidence' in read("docs/android/REAL_DEVICE_SMOKE_CHECKLIST.md")
