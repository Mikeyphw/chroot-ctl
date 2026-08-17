from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def test_module_validator_rejects_retired_webui_artifacts() -> None:
    magisk = read("src/chrootctl/magisk.py")
    assert "FORBIDDEN_MODULE_PATH_TOKENS" in magisk
    for token in (
        "chrootctl-web",
        "chrootctl-webui-service",
        "webui.env",
        "webroot",
        "playwright.config.ts",
        "payload/src/chrootctl/web",
    ):
        assert token in magisk
    assert "forbidden module artifact" in magisk


def test_phase24_keeps_generated_outputs_uncommitted() -> None:
    for rel in ("out", "tmpout"):
        path = ROOT / rel
        assert not (path.is_file() or any(child.is_file() for child in path.rglob("*"))) if path.exists() else True
    for rel in ("chrootctl-magisk.zip", "tmpmod.zip"):
        assert not (ROOT / rel).exists(), rel


def test_phase24_updates_version_and_validator_compatibility() -> None:
    assert any(f'versionName = "0.1.0-phase{phase}"' in read("android/app/build.gradle.kts") for phase in (24, 25, 26, 27, 28, 29))
    assert "token in magisk or token in build_sh" not in read("scripts/validate-android-phase22.py")
    assert "23, 24, 25" in read("scripts/validate-android-phase23.py") or "23, 24, 25, 26" in read("scripts/validate-android-phase23.py")


def test_phase24_documentation_names_the_seal() -> None:
    docs = read("docs/android/PHASE_24_MODULE_REGRESSION_SEAL.md")
    assert "Phase 24" in docs
    assert "Module Regression Seal" in docs
    assert "validate_magisk_module" in docs
