#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    errors: list[str] = []
    matrix = ROOT / "docs/android/WEBUI_PARITY_MATRIX.md"
    docs = ROOT / "docs/android/PHASE_20_21_WEBUI_RETIREMENT.md"
    pyproject = ROOT / "pyproject.toml"
    devtool = ROOT / ".devtool.toml"
    build = ROOT / "android/app/build.gradle.kts"
    manifest = ROOT / "android/app/src/main/AndroidManifest.xml"
    aidl = ROOT / "android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl"
    magisk = ROOT / "src/chrootctl/magisk.py"
    for path in (matrix, docs, pyproject, devtool, build, manifest, aidl, magisk):
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")
    if any(path.is_file() for path in (ROOT / "src/chrootctl/web").glob("**/*")):
        errors.append("src/chrootctl/web must contain no WebUI files")
    for path in ("tests/test_web_app.py", "tests/test_web_jobs.py", "tests/test_web_security.py", "tests/test_transfer_upload.py", "playwright.config.ts"):
        if (ROOT / path).exists():
            errors.append(f"WebUI-only file must be removed: {path}")
    py = read(pyproject)
    for token in ("fastapi", "Jinja2", "uvicorn", "python-multipart", "chrootctl-web", "web/templates", "web/static"):
        if token in py:
            errors.append(f"pyproject still contains WebUI token: {token}")
    if 'console_scripts = ["chrootctl", "chrootctl-app"]' not in read(devtool):
        errors.append("Devtool console_scripts must only verify chrootctl and chrootctl-app")
    matrix_text = read(matrix)
    for token in ("Phase 21 retirement", "Native complete", "Retired", "FastAPI HTTP server", "libsu RootService Binder bridge"):
        if token not in matrix_text:
            errors.append(f"parity matrix missing token: {token}")
    magisk_text = read(magisk)
    if "FORBIDDEN_MODULE_PATH_TOKENS" not in magisk_text:
        for token in ("chrootctl-web", "chrootctl-webui-service", "webui.env", "webroot/index.html", "webroot/icon.svg", "fastapi", "Jinja2", "uvicorn"):
            if token in magisk_text:
                errors.append(f"magisk renderer still contains retired WebUI token: {token}")
    else:
        for token in ("fastapi", "Jinja2", "uvicorn"):
            if token in magisk_text:
                errors.append(f"magisk renderer still contains retired WebUI runtime dependency token: {token}")
    android_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"))
    combined = android_text + read(manifest) + read(aidl)
    for token in ("WebView", "runShell(", "executeArbitraryCommand", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES"):
        if token in combined:
            errors.append(f"forbidden Android token found: {token}")
    if "Manifest.permission.POST_NOTIFICATIONS" in android_text:
        errors.append("Kotlin must not reference Manifest.permission.POST_NOTIFICATIONS directly")
    if "combine(arrayOf" in android_text:
        errors.append("Avoid fragile combine(arrayOf(...)) inference")
    if re.search(r'"/data/', android_text):
        errors.append("Kotlin must not hardcode /data/ path literals")
    build_text = read(build)
    if "compileSdk = 36" not in build_text or "targetSdk = 36" not in build_text:
        errors.append("Android SDK must remain pinned to 36")
    if not any(f'versionName = "0.1.0-phase{phase}"' in build_text for phase in (21, 22, 23, 24, 25, 26, 27, 28, 29)):
        errors.append("Android app versionName must be at least phase21")
    backup_rules = ROOT / "android/app/src/main/res/xml/backup_rules.xml"
    if '@xml/backup_rules' in read(manifest) and not backup_rules.exists():
        errors.append("manifest references @xml/backup_rules but backup_rules.xml is missing")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 20-21 WebUI parity seal and retirement validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
