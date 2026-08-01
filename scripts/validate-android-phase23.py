#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def error_if(errors: list[str], condition: bool, message: str) -> None:
    if condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    build = read(ROOT / "android/app/build.gradle.kts")
    gitignore = read(ROOT / ".gitignore")
    phase22_validator = read(ROOT / "scripts/validate-android-phase22.py")
    docs = read(ROOT / "docs/android/PHASE_23_GENERATED_ARTIFACT_PURGE.md")

    error_if(errors, 'compileSdk = 36' not in build, "compileSdk must remain pinned to 36")
    error_if(errors, 'targetSdk = 36' not in build, "targetSdk must remain pinned to 36")
    error_if(errors, not any(f'versionName = "0.1.0-phase{phase}"' in build for phase in (23, 24, 25, 26, 27)), "versionName must be phase23 or later")

    for rel in ("out", "tmpout"):
        path = ROOT / rel
        error_if(errors, path.is_file() or any(child.is_file() for child in path.rglob("*")) if path.exists() else False, f"generated module output files must not be committed: {rel}")
        error_if(errors, f"{rel}/" not in gitignore, f".gitignore must ignore generated output: {rel}")
    for rel in ("chrootctl-magisk.zip", "tmpmod.zip"):
        error_if(errors, (ROOT / rel).exists(), f"generated module zip must not be committed: {rel}")
        error_if(errors, rel not in gitignore, f".gitignore must ignore generated output: {rel}")

    for rel in (
        "out/webroot",
        "out/bin/chrootctl-webui-service",
        "out/system/bin/chrootctl-web",
        "out/system/bin/chrootctl-webui-service",
        "out/payload/src/chrootctl/web",
        "tmpout/webroot",
        "tmpout/bin/chrootctl-webui-service",
        "tmpout/system/bin/chrootctl-web",
        "tmpout/system/bin/chrootctl-webui-service",
        "tmpout/payload/src/chrootctl/web",
        "tmpout/payload/playwright.config.ts",
    ):
        path = ROOT / rel
        error_if(errors, path.is_file() or any(child.is_file() for child in path.rglob("*")) if path.exists() else False, f"stale WebUI generated artifact returned: {rel}")

    for rel in ("src/chrootctl/web", "playwright.config.ts"):
        error_if(errors, any(path.is_file() for path in (ROOT / rel).rglob("*")) if (ROOT / rel).is_dir() else (ROOT / rel).exists(), f"retired WebUI source returned: {rel}")

    pyproject = read(ROOT / "pyproject.toml")
    for token in ("fastapi", "Jinja2", "uvicorn", "python-multipart", "chrootctl-web"):
        error_if(errors, token in pyproject, f"retired WebUI dependency/script returned: {token}")

    error_if(errors, "range(22, 28)" not in phase22_validator, "phase22 validator must accept phase23/24 release-hardening versions")
    for token in ("Phase 23", "out/", "tmpout/", "WebUI retirement", "SDK remains pinned to 36"):
        error_if(errors, token not in docs, f"phase23 docs missing token: {token}")

    kotlin_root = ROOT / "android/app/src/main/kotlin"
    kotlin = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in kotlin_root.rglob("*.kt"))
    error_if(errors, bool(re.search(r'"/data/', kotlin)), "Kotlin must not hardcode /data/ path literals")
    error_if(errors, "Manifest.permission.POST_NOTIFICATIONS" in kotlin, "Kotlin must not reference POST_NOTIFICATIONS directly")
    error_if(errors, "combine(arrayOf" in kotlin, "fragile combine(arrayOf(...)) inference is forbidden")

    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("Phase 23 generated artifact purge validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
