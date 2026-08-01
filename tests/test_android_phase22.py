from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (repo_root() / rel).read_text(encoding="utf-8", errors="ignore")


def kotlin_sources() -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (repo_root() / "android/app/src/main/kotlin").rglob("*.kt"))


def test_phase22_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(repo_root() / "scripts/validate-android-phase22.py")],
        cwd=repo_root(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "Phase 22 release hardening validator passed" in result.stdout


def test_webui_runtime_remains_retired() -> None:
    root = repo_root()
    assert not any(path.is_file() for path in (root / "src/chrootctl/web").glob("**/*"))
    pyproject = read("pyproject.toml")
    magisk = read("src/chrootctl/magisk.py")
    build_sh = read("build.sh")
    for token in ("fastapi", "Jinja2", "uvicorn", "python-multipart", "chrootctl-web", "webui.env", "webroot"):
        assert token not in pyproject
    for token in ("fastapi", "Jinja2", "uvicorn"):
        assert token not in build_sh
    if "FORBIDDEN_MODULE_PATH_TOKENS" not in magisk:
        for token in ("chrootctl-web", "webui.env", "webroot"):
            assert token not in magisk


def test_android_release_hardening_guardrails() -> None:
    build = read("android/app/build.gradle.kts")
    manifest = read("android/app/src/main/AndroidManifest.xml")
    aidl = read("android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl")
    kotlin = kotlin_sources()
    assert "compileSdk = 36" in build
    assert "targetSdk = 36" in build
    assert any(f'versionName = "0.1.0-phase{phase}"' in build for phase in range(22, 29))
    assert "warningsAsErrors = true" in build
    assert "android.permission.FOREGROUND_SERVICE_DATA_SYNC" in manifest
    assert 'android:foregroundServiceType="dataSync"' in manifest
    assert (repo_root() / "android/app/src/main/res/xml/backup_rules.xml").exists()
    assert (repo_root() / "android/app/src/main/res/xml/data_extraction_rules.xml").exists()
    for icon in (
        "android/app/src/main/res/mipmap-anydpi/ic_launcher.xml",
        "android/app/src/main/res/mipmap-anydpi/ic_launcher_round.xml",
        "android/app/src/main/res/mipmap-anydpi-v33/ic_launcher.xml",
        "android/app/src/main/res/mipmap-anydpi-v33/ic_launcher_round.xml",
    ):
        assert "<monochrome" in read(icon)
    for forbidden in ("WebView", "runShell(", "executeArbitraryCommand", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES"):
        assert forbidden not in kotlin + manifest + aidl
    assert "Manifest.permission.POST_NOTIFICATIONS" not in kotlin
    assert "combine(arrayOf" not in kotlin
    assert not re.search(r'"/data/', kotlin)


def test_fixed_root_ipc_and_transfer_paths_remain_wired() -> None:
    aidl = read("android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl")
    root_service = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt")
    kotlin = kotlin_sources()
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
        assert method in aidl
    assert "transferFromDescriptor" in root_service
    assert "transferToDescriptor" in root_service
    assert "stageImportArchive" in kotlin
    assert "copyManagedArtifactToDocument" in kotlin
    assert "ActivityResultContracts.OpenDocument" in kotlin
    assert "ActivityResultContracts.CreateDocument" in kotlin


def test_release_operations_and_redaction_contracts_remain_available() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    redaction = read("src/chrootctl/bridge/redaction.py")
    operation_service = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt")
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
        assert op in registry
    for sensitive in ("password", "confirmPassword", "confirm_password"):
        assert sensitive in redaction
    for token in ("ACTION_BRIDGE_OPERATION", "EXTRA_OPERATION", "EXTRA_PAYLOAD"):
        assert token in operation_service
