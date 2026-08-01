#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "kotlin" / "com" / "mikeyphw" / "chrootctl"
REGISTRY = ROOT / "src" / "chrootctl" / "bridge" / "registry.py"
STRINGS = ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml"
BUILD = ROOT / "android" / "app" / "build.gradle.kts"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
AIDL = ROOT / "android" / "app" / "src" / "main" / "aidl" / "com" / "mikeyphw" / "chrootctl" / "root" / "IChrootRootService.aidl"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    errors: list[str] = []
    required = [
        REGISTRY,
        ANDROID / "ui" / "tools" / "ToolsScreen.kt",
        ANDROID / "ui" / "MainViewModel.kt",
        ANDROID / "repository" / "BridgeRepository.kt",
        ANDROID / "model" / "UiModels.kt",
        ROOT / "tests" / "test_android_phase18_19.py",
        ROOT / "docs" / "android" / "PHASE_18_19_SYSTEM_DEBUG.md",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")
    registry = read(REGISTRY)
    for token in (
        'OperationSpec("system.runtime"',
        'OperationSpec("system.module_status"',
        'OperationSpec("system.module_build_preview"',
        'OperationSpec("system.module_build"',
        'OperationSpec("support.preview"',
        'OperationSpec("support.bundle"',
        'OperationSpec("repair.preview"',
        'OperationSpec("repair.apply"',
        'OperationSpec("cleanup.temp_preview"',
        'OperationSpec("cleanup.temp"',
        'OperationSpec("debug.probes"',
        'OperationSpec("debug.timeline"',
        'OperationSpec("debug.export"',
    ):
        if token not in registry:
            errors.append(f"missing bridge operation token: {token}")
    for token in ("_system_runtime", "_module_status", "_support_bundle", "_module_build", "_repair_apply", "_debug_probes", "_debug_export"):
        if token not in registry:
            errors.append(f"missing backend handler token: {token}")
    app_text = "\n".join(read(path) for path in ANDROID.rglob("*.kt"))
    for token in (
        "SystemSupportPane",
        "DebugPane",
        "SystemSupportCard",
        "DebugWorkbenchCard",
        "refreshSystemSupport",
        "previewSupportBundle",
        "previewModuleBuild",
        "previewRepair",
        "previewTempCleanup",
        "refreshDebugWorkbench",
        "support.bundle",
        "system.module_build",
        "repair.apply",
        "cleanup.temp",
        "debug.export",
        "debug.probes",
        "debug.timeline",
    ):
        if token not in app_text:
            errors.append(f"missing Android phase18/19 token: {token}")
    forbidden = ("WebView", "runShell(", "executeArbitraryCommand", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES")
    combined = app_text + read(MANIFEST) + read(AIDL)
    for token in forbidden:
        if token in combined:
            errors.append(f"forbidden Android token found: {token}")
    if "Manifest.permission.POST_NOTIFICATIONS" in app_text:
        errors.append("Kotlin must not reference Manifest.permission.POST_NOTIFICATIONS directly")
    if "combine(arrayOf" in app_text:
        errors.append("Avoid fragile combine(arrayOf(...)) inference")
    if re.search(r'"/data/', app_text):
        errors.append("Kotlin must not hardcode /data/ path literals")
    build = read(BUILD)
    if "compileSdk = 36" not in build or "targetSdk = 36" not in build:
        errors.append("Android SDK must remain pinned to 36")
    if 'versionName = "0.1.0-phase19"' not in build and 'versionName = "0.1.0-phase21"' not in build and 'versionName = "0.1.0-phase22"' not in build:
        errors.append("Android app versionName must be at least phase19")
    strings = read(STRINGS)
    for name in (
        "system_support_title",
        "support_bundle_action",
        "module_build_action",
        "repair_apply_action",
        "cleanup_temp_action",
        "debug_workbench_title",
        "debug_run_probes_action",
        "debug_export_action",
    ):
        if f'name="{name}"' not in strings:
            errors.append(f"missing string resource: {name}")
    backup_rules = ROOT / "android" / "app" / "src" / "main" / "res" / "xml" / "backup_rules.xml"
    if '@xml/backup_rules' in read(MANIFEST) and not backup_rules.exists():
        errors.append("manifest references @xml/backup_rules but backup_rules.xml is missing")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 18-19 system, support and debug validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
