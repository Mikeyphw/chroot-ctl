#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise AssertionError(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")

def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)

def main() -> int:
    chroots = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    workflow_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicyTest.kt")
    strings_path = ROOT / "android/app/src/main/res/values/strings.xml"
    ET.parse(strings_path)

    require("enum class ServiceWorkspaceFilter" in policy, "service workspace filter enum missing")
    for token in (
        "serviceWorkspaceFilters",
        "selectedServiceWorkspaceFilter",
        "serviceMatchesWorkspaceFilter",
        "serviceIsRunning",
        "serviceNeedsAttention",
    ):
        require(token in policy, f"service workspace policy missing {token}")

    require("private fun ServicesPanel" in chroots, "ServicesPanel missing")
    services = chroots.split("private fun ServicesPanel", 1)[1].split("private fun userPayload", 1)[0]
    for token in (
        "ServiceFilterButton",
        "FocusedServiceRow",
        "ServiceActionReviewSheet",
        "services_workspace_filters_label",
        "serviceWorkspaceFilters().forEach",
        "selectedServiceWorkspaceFilter",
        "serviceMatchesWorkspaceFilter",
        "serviceStatusTone",
        "serviceActionOperation",
        "action_preview_command",
        "service_action_review_title",
    ):
        require(token in services, f"focused services workspace missing {token}")

    require("private fun ServiceActionButton" not in services, "old per-action duplicate service button helper still present")
    require("private fun ServiceRow(" not in services, "old service row still present in focused workspace section")
    require("action_preview_short" not in services, "services still uses permanent short preview buttons")
    require("onPreviewServicePayload(payload)" in services.split("private fun ServiceActionReviewSheet", 1)[1], "preview is not inside the review sheet")
    focused_row = services.split("private fun FocusedServiceRow", 1)[1].split("private fun ServiceActionReviewSheet", 1)[0]
    require("onPreviewServicePayload" not in focused_row, "service rows still preview directly instead of opening review sheet")
    require("onStartServiceOperation" not in focused_row, "service rows still execute directly instead of opening review sheet")
    require("onSelectServiceAction(service" in focused_row, "service rows do not route actions to review sheet")
    require("StatusPill(service.status" in focused_row, "service rows do not expose status chips")
    require("service_badge_enabled" in focused_row and "service_badge_disabled" in focused_row, "enabled/disabled badges missing")

    strings = strings_path.read_text(encoding="utf-8")
    for key in (
        "services_workspace_title",
        "services_workspace_body",
        "services_workspace_filters_label",
        "services_workspace_no_matches_title",
        "service_filter_all",
        "service_filter_running",
        "service_filter_enabled",
        "service_filter_stale",
        "service_filter_failed",
        "service_action_review_title",
        "action_preview_command",
        "action_cancel",
    ):
        require(f'name="{key}"' in strings, f"missing string resource {key}")

    require("service workspace filters keep noisy service lists focused" in workflow_test, "service policy unit test missing")
    needs_attention = policy.split("fun serviceNeedsAttention", 1)[1].split("fun serviceMatchesWorkspaceFilter", 1)[0]
    require("service.journalText.isNotBlank" not in needs_attention, "journal text alone must not mark services as needing attention")
    require('"inactive"' not in needs_attention and '"unknown"' not in needs_attention, "normal stopped/unknown states must not flood needs-attention filter")
    require("attentionTokens" in needs_attention, "needs-attention matching must be explicit token matching")
    print("Phase 37 focused services workspace validation passed")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
