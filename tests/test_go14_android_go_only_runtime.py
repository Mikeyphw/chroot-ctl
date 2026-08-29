from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_android_runtime_resolver_has_no_python_fallback() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert "pythonCandidates" not in resolver
    assert "chrootctl.bridge.cli" not in resolver
    assert "python-module" not in resolver
    assert "EXPECTED_PYTHON_PACKAGE_VERSION" not in resolver
    assert "LEGACY_COMPATIBILITY_SCHEMA_VERSION" not in resolver
    assert "LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION" not in resolver
    assert "nuitka-onefile" not in resolver
    assert 'NATIVE_RUNTIME_KIND = "go-native"' in resolver
    assert 'EXPECTED_BACKEND_IMPLEMENTATION = "go"' in resolver


def test_android_bridge_process_has_no_python_environment_contract() -> None:
    process = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    assert "PYTHONUNBUFFERED" not in process
    assert "python" not in process.lower()


def test_android_still_allows_go_development_executables_without_module() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert 'File(File.separator, "system/bin/chrootctl")' in resolver
    assert 'File(adbRoot, "chrootctl/bin/chrootctl")' in resolver
    assert 'File(termuxHome, ".local/bin/chrootctl")' in resolver
    assert 'File(termuxUsr, "bin/chrootctl")' in resolver
    assert 'BridgeRuntime(listOf(executable.path, "app"), "chrootctl", executable.path)' in resolver


def test_enabled_module_remains_authoritative_and_fail_closed() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert "if (!activeModuleClaimsAuthority)" in resolver
    assert "external runtime fallback was refused" in resolver
    assert 'File(activeModuleDir, "disable").exists()' in resolver
    assert 'File(activeModuleDir, "remove").exists()' in resolver
