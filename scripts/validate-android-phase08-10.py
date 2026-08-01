#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "kotlin" / "com" / "mikeyphw" / "chrootctl"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
STRINGS = ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml"

REQUIRED = [
    ANDROID / "ui" / "chroots" / "ChrootsScreen.kt",
    ANDROID / "ui" / "activity" / "ActivityScreen.kt",
    ANDROID / "operations" / "ChrootOperationService.kt",
    ANDROID / "operations" / "OperationNotificationController.kt",
]

FORBIDDEN = [
    "WebView",
    "runShell(",
    "executeArbitraryCommand",
    "MANAGE_EXTERNAL_STORAGE",
    "QUERY_ALL_PACKAGES",
]


def main() -> int:
    errors: list[str] = []
    for path in REQUIRED:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")
    chroots = (ANDROID / "ui" / "chroots" / "ChrootsScreen.kt").read_text(encoding="utf-8")
    for token in ("ChrootDetail", "onRefreshDetail", "system.status", "system.doctor"):
        haystack = chroots if token not in {"system.status", "system.doctor"} else (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
        if token not in haystack:
            errors.append(f"missing chroot detail token: {token}")
    activity = (ANDROID / "ui" / "activity" / "ActivityScreen.kt").read_text(encoding="utf-8")
    for token in ("OperationDetail", "OperationEventSummary", "operation_event_line"):
        if token not in activity:
            errors.append(f"missing activity detail token: {token}")
    repository = (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
    for token in ("startSystemRefresh", "recordOperationEvent", "refreshOperationDetail", "cancelOperation"):
        if token not in repository:
            errors.append(f"repository missing operation lifecycle method: {token}")
    manifest = MANIFEST.read_text(encoding="utf-8")
    if ".operations.ChrootOperationService" not in manifest:
        errors.append("foreground operation service is not declared")
    if 'android:foregroundServiceType="dataSync"' not in manifest:
        errors.append("foreground service must declare dataSync type")
    build = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    if "targetSdk = 36" not in build or "compileSdk = 36" not in build:
        errors.append("Android SDK must remain pinned to 36")
    strings = STRINGS.read_text(encoding="utf-8")
    for name in ("action_run_refresh_operation", "operation_notification_channel", "chroot_detail_title", "operation_detail_title"):
        if f'name="{name}"' not in strings:
            errors.append(f"missing string resource: {name}")
    registry = (ROOT / "src" / "chrootctl" / "bridge" / "registry.py").read_text(encoding="utf-8")
    if 'OperationSpec("operations.get"' not in registry:
        errors.append("Python bridge registry does not expose operations.get")
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in ANDROID.rglob("*.kt")) + manifest
    for token in FORBIDDEN:
        if token in text:
            errors.append(f"forbidden Android token found: {token}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 08-10 chroot detail, activity detail, and operation service validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
