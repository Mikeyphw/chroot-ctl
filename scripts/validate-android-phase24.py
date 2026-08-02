#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def error_if(errors: list[str], condition: bool, message: str) -> None:
    if condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    build = read(ROOT / "android/app/build.gradle.kts")
    magisk = read(ROOT / "src/chrootctl/magisk.py")
    phase22 = read(ROOT / "scripts/validate-android-phase22.py")
    phase23 = read(ROOT / "scripts/validate-android-phase23.py")
    docs = read(ROOT / "docs/android/PHASE_24_MODULE_REGRESSION_SEAL.md")

    error_if(errors, 'compileSdk = 36' not in build, "compileSdk must remain pinned to 36")
    error_if(errors, 'targetSdk = 36' not in build, "targetSdk must remain pinned to 36")
    error_if(errors, not any(f'versionName = "0.1.0-phase{phase}"' in build for phase in (24, 25, 26, 27, 28, 29)), "versionName must advance to phase24")

    for token in (
        "FORBIDDEN_MODULE_PATH_TOKENS",
        "validate_magisk_module",
        "retired WebUI artifact returned",
        "chrootctl-web",
        "chrootctl-webui-service",
        "webui.env",
        "webroot",
        "payload/src/chrootctl/web",
    ):
        error_if(errors, token not in magisk, f"Magisk module regression seal missing token: {token}")

    error_if(errors, "token in magisk or token in build_sh" in phase22, "phase22 validator must allow phase24 deny-list mentions")
    error_if(errors, "23, 24, 25" not in phase23 and "23, 24, 25, 26" not in phase23, "phase23 validator must accept later versionNames")

    for rel in ("out", "tmpout"):
        path = ROOT / rel
        error_if(errors, path.is_file() or any(child.is_file() for child in path.rglob("*")) if path.exists() else False, f"generated module output files must not be committed: {rel}")
    for rel in ("chrootctl-magisk.zip", "tmpmod.zip"):
        error_if(errors, (ROOT / rel).exists(), f"generated module zip must not be committed: {rel}")

    for token in ("Phase 24", "Module Regression Seal", "validate_magisk_module", "WebUI", "SDK remains pinned to 36"):
        error_if(errors, token not in docs, f"phase24 docs missing token: {token}")

    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("Phase 24 module regression seal validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
