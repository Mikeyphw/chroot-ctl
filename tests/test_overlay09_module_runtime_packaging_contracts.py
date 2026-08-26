from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_overlay09_active_only_runtime_and_structured_readiness_contract() -> None:
    runtime = text("src/chrootctl/services/module_runtime.py")
    magisk = text("src/chrootctl/magisk.py")
    android = text("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert 'ACTIVE_MODULE_ROOT = Path("/data/adb/modules")' in runtime
    assert 'PENDING_MODULE_ROOTS' in runtime
    assert '_regular_file_in_module' in runtime
    assert '_canonical_module_dir' in runtime
    assert 'runtimeReadiness' in runtime
    assert 'bundled-native' in runtime
    assert 'validate_native_runtime_artifact' in runtime
    assert 'dependencies.ready.json' not in runtime
    assert 'ACTIVE_MODULE_ROOT = Path("/data/adb/modules")' in runtime
    assert 'DEFAULT_MODULE_ID = "chrootctl-magisk"' in magisk
    assert '[ ! -L "$_active" ]' in magisk
    assert 'pending chrootctl module update exists' in magisk
    assert '. "$MODDIR/config/chrootctl/python.env"' not in magisk
    assert 'startup target boot failed; boot orchestration failed' in magisk
    module_boot = text("src/chrootctl/module_boot.py")
    assert "__module-boot" in magisk
    assert "module.boot.start" in module_boot
    assert "OperationManager" in module_boot
    assert '"$CLI" --name "$name" mount' not in magisk
    assert "archive.testzip()" in magisk
    assert "refusing module service outside active module" in magisk
    assert 'modules_update/chrootctl-magisk/system/bin/chrootctl' not in android
    assert 'canonicalFile' in android
    assert 'isSymbolicLink' in android
    assert 'activeModuleClaimsAuthority' in android
    assert 'external runtime fallback was refused' in android
    assert 'NATIVE_RUNTIME_ENTRYPOINT' in android


def test_overlay09_deep_packaging_and_compatibility_contract() -> None:
    magisk = text("src/chrootctl/magisk.py")
    build = text("build.sh")
    compat = text("docs/release/compatibility-manifest.json")
    for token in ("validate_magisk_zip", "FORBIDDEN_MODULE_SUFFIXES", "REQUIRED_MODULE_PATHS", "_ALLOWED_MODULE_DIRS", "REQUIRED_EXECUTABLE_PATHS", "external_attr", "duplicate entry names", "non-regular entry", "_validate_release_identity_sources"):
        assert token in magisk
    assert "validate_magisk_zip" in build
    assert "refusing to clean a non-empty custom OUT_DIR" in build
    assert '"schemaVersion": 2' in compat
    assert '"id": "chrootctl-magisk"' in compat
    assert '"versionCode": 15' in compat

def test_overlay09_release_build_is_host_independent_and_deterministic() -> None:
    magisk = text("src/chrootctl/magisk.py")
    manage = text("manage_source.py")
    build = text("build.sh")
    runtime = text("src/chrootctl/services/module_runtime.py")
    android = text("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert "startup_targets=()" in manage
    assert "create_service_container" not in manage
    assert "wheelhouse" not in manage.lower()
    assert "date_time=(1980, 1, 1, 0, 0, 0)" in magisk
    assert "compresslevel=9" in magisk
    assert "dependencyContractSha256" in magisk
    assert "runtime-manifest.json" in runtime
    assert "bundled-native" in runtime
    assert "static-python-env" not in runtime
    assert "DEFAULT_MODULE_VERSION_CODE" in runtime
    assert "ANDROID_APP_VERSION_NAME" in runtime
    assert "EXPECTED_MODULE_VERSION" in android
    assert "MIN_SUPPORTED_MODULE_VERSION_CODE" in android
    assert "EXPECTED_ANDROID_VERSION_NAME" in android
    assert "ZIP_NAME must stay inside the repository" in build


def test_overlay09_boot_lock_and_dependency_contract_fail_closed() -> None:
    magisk = text("src/chrootctl/magisk.py")
    for token in ("/proc/sys/kernel/random/boot_id", "start_time", "dependencyContractSha256", "DEPENDENCY_MODE=static-python-env", "DEPENDENCY_INSTALL_PHASE=none", "DEPENDENCY_NETWORK=disabled", "DEPENDENCY_REPAIR=disabled"):
        assert token in magisk
    assert "offline_wheelhouse_dir" not in magisk
    assert "ZipInfo.from_file" not in magisk

