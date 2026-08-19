from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def test_phase34c_runtime_resolver_executes_active_module_only() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert 'File(adbRoot, "modules/chrootctl-magisk")' in resolver
    assert 'File(activeModuleDir, "system/bin/chrootctl")' in resolver
    assert 'modules_update/chrootctl-magisk' in resolver
    assert 'pendingModuleDirs.filter(File::exists)' in resolver
    assert 'modules_update/chrootctl-magisk/system/bin/chrootctl' not in resolver
    assert 'ksu/modules/chrootctl-magisk/system/bin/chrootctl' not in resolver
    assert 'File(activeModuleDir, "disable").exists()' in resolver
    assert 'File(activeModuleDir, "remove").exists()' in resolver


def test_phase34c_invalid_override_falls_back_and_protocol_probe_is_required() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert "overrideFailure" in resolver
    assert "normal active-runtime discovery continued" in resolver
    assert "selectCompatibleRuntime(candidates, ::isCompatible)" in resolver
    assert 'listOf("capabilities")' in resolver
    assert 'File(termuxHome, ".local/bin/chrootctl")' in resolver
    assert 'File(termuxUsr, "bin/chrootctl")' in resolver
    assert "pythonCandidates" in resolver


def test_phase34c_lint_api36_and_active_only_docs_are_preserved() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    docs = read("docs/android/PHASE_34C_ROOT_MODULE_RUNTIME_RESOLVER.md")
    assert "compileSdk = 36" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"\s*/>', lint)
    assert ignored == ["OldTargetApi"]
    assert "/data/adb/modules/chrootctl-magisk/system/bin/chrootctl" in docs
    assert "pending updates are diagnostics only" in docs.lower()
    assert "protocol-1" in docs
