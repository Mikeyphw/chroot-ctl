from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def test_generated_module_outputs_are_not_committed() -> None:
    for rel in ("out", "tmpout"):
        path = ROOT / rel
        assert not (path.is_file() or any(child.is_file() for child in path.rglob("*"))) if path.exists() else True
    for rel in ("chrootctl-magisk.zip", "tmpmod.zip"):
        assert not (ROOT / rel).exists(), rel


def test_gitignore_blocks_generated_module_outputs() -> None:
    gitignore = read(".gitignore")
    for token in ("out/", "tmpout/", "chrootctl-magisk.zip", "tmpmod.zip"):
        assert token in gitignore


def test_phase23_keeps_webui_retired() -> None:
    assert not any(path.is_file() for path in (ROOT / "src/chrootctl/web").rglob("*"))
    assert "chrootctl-web" not in read("pyproject.toml")
    assert "fastapi" not in read("pyproject.toml")


def test_phase23_sdk_and_validator_forward_compatibility() -> None:
    build = read("android/app/build.gradle.kts")
    assert "compileSdk = 36" in build
    assert "targetSdk = 36" in build
    assert 'versionName = "0.1.0-phase23"' in build or 'versionName = "0.1.0-phase24"' in build
    assert "range(22, 25)" in read("scripts/validate-android-phase22.py")
