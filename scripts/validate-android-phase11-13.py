#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "kotlin" / "com" / "mikeyphw" / "chrootctl"
STRINGS = ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml"
BUILD = ROOT / "android" / "app" / "build.gradle.kts"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"


def main() -> int:
    errors: list[str] = []
    required = [
        ANDROID / "ui" / "install" / "InstallScreen.kt",
        ANDROID / "operations" / "ChrootOperationService.kt",
        ROOT / "src" / "chrootctl" / "bridge" / "registry.py",
        ROOT / "tests" / "test_android_phase11_13.py",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")
    registry = (ROOT / "src" / "chrootctl" / "bridge" / "registry.py").read_text(encoding="utf-8")
    for token in (
        'OperationSpec("install.form"',
        'OperationSpec("install.preview"',
        'OperationSpec("install.run"',
        'OperationSpec("chroots.lifecycle.preview"',
        'OperationSpec("chroots.start"',
        'OperationSpec("chroots.restart"',
        'OperationSpec("chroots.remove.execute"',
        'OperationSpec("snapshots.list"',
        'OperationSpec("snapshots.preview"',
        'OperationSpec("snapshots.create"',
        'OperationSpec("snapshots.restore"',
        'OperationSpec("snapshots.export"',
    ):
        if token not in registry:
            errors.append(f"missing bridge operation token: {token}")
    app_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in ANDROID.rglob("*.kt"))
    for token in (
        "InstallScreen",
        "LifecyclePanel",
        "SnapshotPanel",
        "ACTION_BRIDGE_OPERATION",
        "PreviewSummary",
        "onExecuteRemove",
        "removePayloadJson",
        "onStartSnapshotRestore",
        "onStartSnapshotExport",
        "snapshotRestorePayloadJson",
        "snapshotExportPayloadJson",
    ):
        if token not in app_text:
            errors.append(f"missing Android phase 11-13 token: {token}")
    forbidden = ("WebView", "runShell(", "executeArbitraryCommand", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES")
    for token in forbidden:
        if token in app_text + MANIFEST.read_text(encoding="utf-8"):
            errors.append(f"forbidden Android token found: {token}")
    build = BUILD.read_text(encoding="utf-8")
    if "compileSdk = 36" not in build or "targetSdk = 36" not in build:
        errors.append("Android SDK must remain pinned to 36")
    if not any(token in build for token in (
        'versionName = "0.1.0-phase13"',
        'versionName = "0.1.0-phase14"',
        'versionName = "0.1.0-phase15"',
        'versionName = "0.1.0-phase16"',
        'versionName = "0.1.0-phase17"',
        'versionName = "0.1.0-phase18"',
        'versionName = "0.1.0-phase19"',
        'versionName = "0.1.0-phase20"',
        'versionName = "0.1.0-phase21"',
        'versionName = "0.1.0-phase22"',
        'versionName = "0.1.0-phase24"',
        'versionName = "0.1.0-phase25"',
        'versionName = "0.1.0-phase26"',
        'versionName = "0.1.0-phase23"',
    )):
        errors.append("Android app versionName must be at least phase13")
    strings = STRINGS.read_text(encoding="utf-8")
    for name in (
        "nav_install",
        "install_native_title",
        "lifecycle_actions_title",
        "snapshot_actions_title",
        "action_remove_chroot",
        "lifecycle_remove_confirmation_label",
        "snapshot_restore_confirmation_label",
        "action_restore_snapshot",
        "action_export_snapshot",
    ):
        if f'name="{name}"' not in strings:
            errors.append(f"missing string resource: {name}")
    backup_rules = ROOT / "android" / "app" / "src" / "main" / "res" / "xml" / "backup_rules.xml"
    if '@xml/backup_rules' in MANIFEST.read_text(encoding="utf-8") and not backup_rules.exists():
        errors.append("manifest references @xml/backup_rules but backup_rules.xml is missing")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 11-13 install, lifecycle, snapshots and recovery validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
