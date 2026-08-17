#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    activity = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/activity/ActivityScreen.kt")
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    vm = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt")
    registry = read("src/chrootctl/bridge/registry.py")
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")

    require("targetSdk = 36" in build and "compileSdk = 37" in build, "Phase 33 must preserve compileSdk 37 / targetSdk 36")
    require(re.findall(r'id="([^"]+)"', lint) == ["OldTargetApi"], "lint.xml must ignore only OldTargetApi")
    require("OperationActivityFilter" in activity and "FilterChip" in activity, "Activity filters missing")
    for token in ["onCancelOperation", "onRetryOperation", "onRetryWithFixes", "onRecoverLatestSnapshot", "AlertDialog", "previewRetryOperation", "previewRetryWithFixes"]:
        require(token in activity, f"Activity recovery token missing: {token}")
    require("onPreviewRetryWithFixes" in activity and "operation_retry_fixes_preview_action" in activity, "Activity retry actions must be preview-first")
    require("operation_retry_preview_body" in activity and "operation_retry_fixes_preview_body" in activity, "Retry preview copy must be string-backed")
    for token in ["WorkspaceSelector", "LogsWorkspaceCard", "RepairWorkspaceCard", "HelpAndApiCard", "LaunchedEffect", "delay(3_000L)"]:
        require(token in tools, f"Focused Tools workspace token missing: {token}")
    require("RepairItemSummary" in models and "selectedRepairItemIds" in models, "Selective repair model missing")
    require("repairDecisionsJson" in vm and 'put("decisions"' in vm and "applyAll" not in vm, "Repair payload must use explicit decisions, not applyAll")
    require('OperationSpec("operations.retry"' in registry, "operations.retry bridge operation missing")
    require("REDACTED_RETRY_REQUEST" in registry and "_contains_redacted" in registry, "Retry redaction guard missing")
    require('onStartBridgeOperation("operations.retry"' in app, "Android retry action not wired")
    require("viewModel.refreshSnapshots(target)" in app, "Activity snapshot recovery must refresh target snapshots before handoff")
    require("REPAIR_DECISIONS_REQUIRED" in registry and "REPAIR_DECISIONS_EMPTY" in registry, "repair.apply must require explicit decisions")
    require("INVALID_RETRY_MODE" in registry, "operations.retry must reject unsupported modes")
    require("WebView" not in tools + activity + app, "Phase 33 must not reintroduce WebView")
    ET.parse(ROOT / "android/app/src/main/res/values/strings.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
