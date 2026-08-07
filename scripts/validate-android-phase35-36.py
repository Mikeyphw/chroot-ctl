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
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    chroots = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    bridge_models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModels.kt")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    ui_message = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/UiMessagePolicy.kt")
    bridge_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModelsTest.kt")
    workflow_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicyTest.kt")
    strings_path = ROOT / "android/app/src/main/res/values/strings.xml"

    require("compileSdk = 36" in build and "targetSdk = 36" in build, "API 36 contract changed")
    require("warningsAsErrors = true" in build and "abortOnError = true" in build, "strict lint policy changed")
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"', lint)
    require("OldTargetApi" in ignored, f"OldTargetApi suppression missing: {ignored}")
    require("WarningsAsErrors" not in ignored and "ObsoleteLintCustomCheck" not in ignored, f"broad lint suppression introduced: {ignored}")

    for token in (
        "enum class ChrootWorkspaceTab",
        "Overview",
        "Services",
        "Users",
        "Snapshots",
        "Advanced",
        "chrootListIsWorkspaceLauncherOnly",
        "bridgeShapePrimaryMessage",
        "isBridgeShapeError",
    ):
        require(token in policy, f"workspace policy missing {token}")

    for token in (
        "ChrootWorkspaceLauncher",
        "ChrootWorkspaceScreen",
        "WorkspaceOverviewTab",
        "AdvancedWorkspaceTab",
        "BridgePaneError",
        "action_open_workspace",
        "chroot_workspace_tabs_label",
        "ChrootWorkspaceTab.Services",
        "ChrootWorkspaceTab.Users",
        "ChrootWorkspaceTab.Snapshots",
        "ChrootWorkspaceTab.Advanced",
    ):
        require(token in chroots, f"chroot workspace UI missing {token}")

    top_level_card = chroots.split("private fun Phase32ChrootCard", 1)[1].split("private fun ChrootWorkspaceScreen", 1)[0]
    require("UsersPanel(" not in top_level_card and "ServicesPanel(" not in top_level_card, "top-level chroot card renders inline management panels")
    require("onPreviewLifecycle(chroot.name, \"remove\")" not in top_level_card, "top-level card exposes remove instead of workspace danger zone")
    require("action_open_workspace" in top_level_card, "top-level chroot cards do not open workspace")
    require("LifecyclePanel(" in chroots.split("private fun AdvancedWorkspaceTab", 1)[1], "danger-zone lifecycle panel is not isolated in Advanced")

    for token in ("requireDataOrWrappedArray", "requireArrayFromData"):
        require(token in bridge_models, f"bridge shape adapter missing {token}")
    require('requireDataOrWrappedArray("checks", "system.status")' in repository, "system.status array adapter missing")
    require('requireDataOrWrappedArray("checks", "system.doctor")' in repository, "system.doctor array adapter missing")
    require('requireArrayFromData("services", "items")' in repository, "services list object-wrapper adapter missing")
    require('requireArrayFromData("users", "items")' in repository, "users list object-wrapper adapter missing")
    require('requireArrayFromData("snapshots", "items")' in repository, "snapshot list object-wrapper adapter missing")
    require('"bridge response data was" in message' in ui_message, "bridge-shape errors are not classified as invalid responses")

    for token in (
        "array detail payload can be wrapped as checks",
        "array lists can be read from object wrappers",
    ):
        require(token in bridge_test, f"BridgeModelsTest missing {token}")
    for token in (
        "chroot list launches workspace instead of rendering inline management",
        "bridge shape errors become human readable workspace messages",
    ):
        require(token in workflow_test, f"WorkflowUxPolicyTest missing {token}")

    parsed = ET.parse(strings_path)
    string_names = {node.attrib["name"] for node in parsed.getroot() if node.tag == "string"}
    references: set[str] = set()
    for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"):
        references.update(re.findall(r"R\.string\.([A-Za-z0-9_]+)", path.read_text(encoding="utf-8")))
    missing = sorted(references - string_names)
    require(not missing, f"missing string resources: {missing}")

    kotlin = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"))
    require("WebView" not in kotlin, "WebView trust boundary introduced")
    require("Runtime.getRuntime().exec" not in kotlin, "arbitrary process execution introduced")
    require("http://" not in kotlin and "https://" not in kotlin, "HTTP surface introduced")

    print("Phase 35-36 chroot workspace and bridge-shape validation passed")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
