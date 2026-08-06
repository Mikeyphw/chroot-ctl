from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def test_phase34c_runtime_resolver_prefers_repo_root_module_launcher_paths() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    expected_in_order = [
        'File(adbRoot, "modules/chrootctl-magisk/system/bin/chrootctl")',
        'File(adbRoot, "modules_update/chrootctl-magisk/system/bin/chrootctl")',
        'File(ksuRoot, "modules/chrootctl-magisk/system/bin/chrootctl")',
        'File(ksuRoot, "modules_update/chrootctl-magisk/system/bin/chrootctl")',
        'File(File.separator, "system/bin/chrootctl")',
        'File(adbRoot, "chrootctl/bin/chrootctl")',
        'File(termuxHome, ".local/bin/chrootctl")',
        'File(termuxUsr, "bin/chrootctl")',
    ]
    positions = [resolver.find(token) for token in expected_in_order]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)
    assert "rootModuleExecutableCandidates" in resolver
    assert "ksuRoot" in resolver


def test_phase34c_runtime_resolver_keeps_protocol_probe_and_fallbacks() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert "selectCompatibleRuntime(candidates, ::isCompatible)" in resolver
    assert 'listOf("capabilities")' in resolver
    assert 'File(termuxHome, ".local/bin/chrootctl")' in resolver
    assert 'File(termuxUsr, "bin/chrootctl")' in resolver
    assert "pythonCandidates" in resolver
    assert "CHROOTCTL_EXECUTABLE" in resolver
    assert "Magisk/KSU module" in resolver
    assert '"/data/' not in resolver


def test_phase34c_lint_api36_and_docs_are_preserved() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    docs = read("docs/android/PHASE_34C_ROOT_MODULE_RUNTIME_RESOLVER.md")
    assert "compileSdk = 36" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"\s*/>', lint)
    assert ignored == ["OldTargetApi"]
    assert "chrootctl-magisk" in docs
    assert "/data/adb/modules/chrootctl-magisk/system/bin/chrootctl" in docs
    assert "/data/adb/ksu/modules/chrootctl-magisk/system/bin/chrootctl" in docs
    assert "protocol-1" in docs
