#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def error_if(errors: list[str], condition: bool, message: str) -> None:
    if condition:
        errors.append(message)


def all_kotlin() -> str:
    root = ROOT / "android/app/src/main/kotlin"
    return "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in root.rglob("*.kt"))


def main() -> int:
    errors: list[str] = []
    android_build = ROOT / "android/app/build.gradle.kts"
    manifest_path = ROOT / "android/app/src/main/AndroidManifest.xml"
    aidl_path = ROOT / "android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl"
    pyproject_path = ROOT / "pyproject.toml"
    magisk_path = ROOT / "src/chrootctl/magisk.py"
    build_sh_path = ROOT / "build.sh"
    registry_path = ROOT / "src/chrootctl/bridge/registry.py"
    bridge_repo_path = ROOT / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt"
    operation_service_path = ROOT / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt"
    root_service_path = ROOT / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt"
    docs_path = ROOT / "docs/android/PHASE_22_RELEASE_HARDENING.md"

    for path in (
        android_build,
        manifest_path,
        aidl_path,
        pyproject_path,
        magisk_path,
        build_sh_path,
        registry_path,
        bridge_repo_path,
        operation_service_path,
        root_service_path,
        docs_path,
    ):
        error_if(errors, not path.exists(), f"missing required file: {path.relative_to(ROOT)}")
    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1

    build = read(android_build)
    manifest = read(manifest_path)
    aidl = read(aidl_path)
    kotlin = all_kotlin()
    pyproject = read(pyproject_path)
    magisk = read(magisk_path)
    build_sh = read(build_sh_path)
    registry = read(registry_path)
    bridge_repo = read(bridge_repo_path)
    operation_service = read(operation_service_path)
    root_service = read(root_service_path)
    docs = read(docs_path)

    # SDK and Android build contract.
    error_if(errors, "compileSdk = 36" not in build, "compileSdk must remain pinned to 36")
    error_if(errors, "targetSdk = 36" not in build, "targetSdk must remain pinned to 36")
    error_if(
        errors,
        not any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(22, 27)),
        "Android versionName must be phase22 or later release-hardening phase",
    )
    error_if(errors, "warningsAsErrors = true" not in build, "lint warnings must remain errors")
    error_if(errors, "abortOnError = true" not in build, "lint must abort on errors")

    # Manifest/resource contract.
    for permission in (
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
        "android.permission.WAKE_LOCK",
    ):
        error_if(errors, permission not in manifest, f"manifest missing required permission: {permission}")
    for forbidden_permission in (
        "MANAGE_EXTERNAL_STORAGE",
        "READ_EXTERNAL_STORAGE",
        "WRITE_EXTERNAL_STORAGE",
        "READ_MEDIA_IMAGES",
        "READ_MEDIA_VIDEO",
        "QUERY_ALL_PACKAGES",
    ):
        error_if(errors, forbidden_permission in manifest, f"forbidden broad permission found: {forbidden_permission}")
    error_if(errors, 'android:foregroundServiceType="dataSync"' not in manifest, "operation service must declare dataSync foreground service type")
    error_if(errors, '@xml/backup_rules' in manifest and not (ROOT / "android/app/src/main/res/xml/backup_rules.xml").exists(), "backup_rules.xml missing while referenced")
    error_if(errors, '@xml/data_extraction_rules' in manifest and not (ROOT / "android/app/src/main/res/xml/data_extraction_rules.xml").exists(), "data_extraction_rules.xml missing while referenced")
    icon_files = [
        ROOT / "android/app/src/main/res/mipmap-anydpi/ic_launcher.xml",
        ROOT / "android/app/src/main/res/mipmap-anydpi/ic_launcher_round.xml",
        ROOT / "android/app/src/main/res/mipmap-anydpi-v33/ic_launcher.xml",
        ROOT / "android/app/src/main/res/mipmap-anydpi-v33/ic_launcher_round.xml",
    ]
    for icon in icon_files:
        error_if(errors, not icon.exists(), f"missing adaptive icon: {icon.relative_to(ROOT)}")
        if icon.exists():
            error_if(errors, "<monochrome" not in read(icon), f"adaptive icon missing monochrome tag: {icon.relative_to(ROOT)}")
    error_if(errors, not (ROOT / "android/app/src/main/res/drawable/ic_launcher_monochrome.xml").exists(), "missing monochrome drawable")

    # WebUI retirement must stay retired.
    error_if(errors, any(path.is_file() for path in (ROOT / "src/chrootctl/web").glob("**/*")), "src/chrootctl/web must remain retired")
    for rel in ("tests/test_web_app.py", "tests/test_web_jobs.py", "tests/test_web_security.py", "tests/test_transfer_upload.py", "playwright.config.ts"):
        error_if(errors, (ROOT / rel).exists(), f"retired WebUI/browser test file returned: {rel}")
    for token in ("fastapi", "Jinja2", "uvicorn", "python-multipart", "chrootctl-web", "web/templates", "web/static"):
        error_if(errors, token in pyproject, f"pyproject contains retired WebUI token: {token}")
    # Phase 24 allows Magisk/build validators to mention retired tokens as forbidden-output checks.
    # Runtime module generation must still reject them through validate_magisk_module.
    for token in ("fastapi", "Jinja2", "uvicorn"):
        error_if(errors, token in build_sh, f"build script contains retired WebUI runtime token: {token}")
    for path in (ROOT / "src/chrootctl").rglob("*.py"):
        if path.name.endswith(".py"):
            text = read(path)
            error_if(errors, "chrootctl.web" in text or "..web" in text, f"WebUI import found in {path.relative_to(ROOT)}")

    # Fixed privileged IPC contract.
    combined_android = kotlin + "\n" + manifest + "\n" + aidl
    for token in ("WebView", "runShell(", "executeArbitraryCommand", "Runtime.getRuntime().exec", "ProcessBuilder(\"su\"", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES"):
        error_if(errors, token in combined_android, f"forbidden Android token found: {token}")
    for method in (
        "String serviceInfo()",
        "String capabilities()",
        "String query(String requestJson)",
        "String preview(String requestJson)",
        "String startOperation(String requestJson, in ParcelFileDescriptor output)",
        "String operationState(String operationId)",
        "String cancelOperation(String operationId)",
        "String transferFromDescriptor(String requestJson, in ParcelFileDescriptor input)",
        "String transferToDescriptor(String requestJson, in ParcelFileDescriptor output)",
    ):
        error_if(errors, method not in aidl, f"AIDL missing fixed method: {method}")

    # Android lint traps already seen in this project.
    error_if(errors, "Manifest.permission.POST_NOTIFICATIONS" in kotlin, "Kotlin must not reference Manifest.permission.POST_NOTIFICATIONS directly")
    error_if(errors, "combine(arrayOf" in kotlin, "fragile combine(arrayOf(...)) inference is forbidden")
    error_if(errors, bool(re.search(r'"/data/', kotlin)), "Kotlin must not hardcode /data/ path literals")

    # Storage Access Framework and descriptor transfer must remain wired.
    for token in ("ActivityResultContracts.OpenDocument", "ActivityResultContracts.CreateDocument"):
        error_if(errors, token not in kotlin, f"SAF contract missing from Kotlin: {token}")
    for token in ("transferFromDescriptor", "transferToDescriptor"):
        error_if(errors, token not in aidl or token not in root_service, f"descriptor transfer path missing: {token}")
    error_if(errors, "stageImportArchive" not in kotlin, "Android import flow must stage imports through controlled storage")
    error_if(errors, "copyManagedArtifactToDocument" not in kotlin, "Android export flow must copy managed artifacts to document descriptors")

    # Operation contracts after WebUI retirement.
    for op in (
        "install.run",
        "chroots.start",
        "chroots.restart",
        "chroots.remove.execute",
        "snapshots.restore",
        "users.set_password",
        "services.restart",
        "catalog.apply",
        "transfer.import",
        "transfer.export",
        "system.module_build",
        "support.bundle",
        "repair.apply",
        "cleanup.temp",
        "debug.export",
    ):
        error_if(errors, op not in registry, f"bridge registry missing release operation: {op}")
    for sensitive in ("password", "confirmPassword", "confirm_password"):
        error_if(errors, sensitive not in read(ROOT / "src/chrootctl/bridge/redaction.py"), f"redaction helper missing sensitive key: {sensitive}")
    for token in ("ACTION_BRIDGE_OPERATION", "EXTRA_OPERATION", "EXTRA_PAYLOAD"):
        error_if(errors, token not in operation_service, f"generic foreground operation wiring missing: {token}")

    # Documentation and parity gates must describe this phase.
    for token in (
        "Phase 22",
        "Release hardening",
        "SDK 36",
        "WebUI remains retired",
        "Storage Access Framework",
        "fixed AIDL",
        "destructive actions",
    ):
        error_if(errors, token not in docs, f"phase22 docs missing token: {token}")

    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("Phase 22 release hardening validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
