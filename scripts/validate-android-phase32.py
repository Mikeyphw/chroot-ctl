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
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicy.kt")
    chroots = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    install = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/install/InstallScreen.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    registry = read("src/chrootctl/bridge/registry.py")
    preview_service = read("src/chrootctl/services/preview.py")
    unit = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicyTest.kt")
    strings_path = ROOT / "android/app/src/main/res/values/strings.xml"

    require("compileSdk = 36" in build and "targetSdk = 36" in build, "API 36 contract changed")
    require("warningsAsErrors = true" in build and "abortOnError = true" in build, "strict lint policy changed")
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"', lint)
    require(ignored == ["OldTargetApi"], f"unexpected ignored lint issues: {ignored}")

    for token in ("ChrootListFilter", "chrootMatchesQuery", "chrootMatchesFilter", "validateInstallDraft", "CHROOT_NAME_PATTERN", "USERNAME_PATTERN"):
        require(token in policy, f"workflow policy missing {token}")
    for token in ("rememberSaveable", "chroots_search_label", "ChrootFilterButton", "Phase32ChrootCard", "ActionFlowRow", "chrootMatchesQuery", "chrootMatchesFilter"):
        require(token in chroots, f"Chroots redesign missing {token}")
    require('onPreviewLifecycle(chroot.name, "upgrade")' in chroots, "upgrade preview not exposed from chroot cards")
    require('onStartLifecycle(chroot.name, "chroots.restart")' in chroots, "contextual restart action missing")
    require('onStartLifecycle(chroot.name, "chroots.upgrade")' in chroots, "contextual upgrade action missing")
    require('onStartLifecycle(chroot.name, "chroots.start")' in chroots, "contextual start action missing")
    compact_card = chroots.split("private fun Phase32ChrootCard", 1)[1].split("private fun ChrootDetailCard", 1)[0]
    require('onPreviewLifecycle(chroot.name, "remove")' in compact_card, "compact chroot card lacks remove preview entry point")
    require('onExecuteRemove(chroot.name, removeConfirmation)' in chroots, "typed remove confirmation gate missing")
    require("Row(horizontalArrangement = Arrangement.spacedBy(8.dp))" not in chroots, "fixed-width button rows remain in chroots screen")

    for token in ("InstallWizardStep", "InstallWizardStepper", "DistroChoiceStep", "ConfigureInstallStep", "ReviewInstallStep", "rememberSaveable", "AnimatedVisibility", "validateInstallDraft", "install_show_advanced", "onOpenActivity"):
        require(token in install, f"Install wizard missing {token}")
    require("install_distro_error" in install, "distro validation is not shown on the choose step")
    require("InstallWizardStep.Configure -> validation.valid" in install, "Configure step can advance with invalid name or username")
    require("if (step != InstallWizardStep.Review)" in install, "Review footer still exposes an inert Continue button")
    require("install_foreground_handoff_body" in install and "LinearProgressIndicator" in install, "foreground progress handoff missing")
    require("PreviewCard(summary = summary" in install, "preview-first install card missing")
    require("isError = !valid" in install, "field-level validation missing")
    require("onOpenActivity = openActivity" in app, "Install screen is not wired to Activity progress")

    require("def _upgrade_chroot" in registry, "bridge upgrade operation handler missing")
    require('OperationSpec("chroots.upgrade"' in registry, "chroots.upgrade operation not registered")
    require("services.preview().upgrade" in registry and "services.install().upgrade" in registry, "upgrade is not preview-first")
    upgrade_section = registry.split("def _upgrade_chroot", 1)[1].split("def _remove_chroot", 1)[0]
    require("preview_ok = bool(preview.get(\"ok\", len(blocking) == 0))" in upgrade_section, "upgrade execution is not defensive against preview shape drift")
    require("cancelled()" in upgrade_section, "upgrade operation lacks cancellation checks")
    preview_upgrade = preview_service.split("def upgrade", 1)[1].split("def", 1)[0]
    require('"ok": ok' in preview_upgrade and '"message": "Upgrade preview is ready." if ok else "Upgrade preview has blocking issues."' in preview_upgrade, "upgrade preview does not expose Android-compatible ok/message fields")
    require('blocking = [] if bool(record.get("path"))' in preview_upgrade, "upgrade preview does not derive blocking issues from registered path")

    for token in ("chroot search covers distro status path and health", "chroot filters separate running stopped and attention", "install draft validation is strict"):
        require(token in unit, f"policy unit test missing: {token}")

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

    print("Phase 32 chroots and install workflow redesign validation passed")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
