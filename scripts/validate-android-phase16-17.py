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
    for path in (
        REGISTRY,
        AIDL,
        ANDROID / "MainActivity.kt",
        ANDROID / "ui" / "tools" / "ToolsScreen.kt",
        ANDROID / "ui" / "MainViewModel.kt",
        ANDROID / "repository" / "BridgeRepository.kt",
        ANDROID / "model" / "UiModels.kt",
        ROOT / "tests" / "test_android_phase16_17.py",
        ROOT / "docs" / "android" / "PHASE_16_17_CATALOG_TRANSFER.md",
    ):
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    registry = read(REGISTRY)
    for token in (
        'OperationSpec("catalog.tools"',
        'OperationSpec("catalog.addons"',
        'OperationSpec("catalog.search"',
        'OperationSpec("catalog.preview"',
        'OperationSpec("catalog.apply"',
        'OperationSpec("packages.inventory"',
        'OperationSpec("packages.compare"',
        'OperationSpec("transfer.inspect_import"',
        'OperationSpec("transfer.import"',
        'OperationSpec("transfer.preview_export"',
        'OperationSpec("transfer.export"',
        'OperationSpec("artifacts.list"',
        'OperationSpec("artifacts.cleanup"',
    ):
        if token not in registry:
            errors.append(f"missing bridge operation token: {token}")
    for token in ("_catalog_preview", "_catalog_apply", "_packages_inventory", "_transfer_import", "_transfer_export", "_artifacts_cleanup"):
        if token not in registry:
            errors.append(f"missing backend handler token: {token}")

    app_text = "\n".join(read(path) for path in ANDROID.rglob("*.kt"))
    for token in (
        "CatalogPane",
        "CatalogEntrySummary",
        "PackagePane",
        "TransferPane",
        "refreshCatalog",
        "previewCatalogApply",
        "catalog.apply",
        "packages.inventory",
        "packages.compare",
        "transfer.inspect_import",
        "transfer.import",
        "transfer.export",
        "artifacts.cleanup",
        "ActivityResultContracts.OpenDocument",
        "ActivityResultContracts.CreateDocument",
        "transferFromDescriptor",
        "transferToDescriptor",
    ):
        if token not in app_text:
            errors.append(f"missing Android catalog/transfer token: {token}")

    aidl = read(AIDL)
    for token in ("transferFromDescriptor", "transferToDescriptor"):
        if token not in aidl:
            errors.append(f"missing fixed AIDL transfer method: {token}")
    forbidden = ("WebView", "runShell(", "executeArbitraryCommand", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES")
    combined = app_text + read(MANIFEST) + aidl
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
    if "versionName = \"0.1.0-phase17\"" not in build and "versionName = \"0.1.0-phase19\"" not in build:
        errors.append("Android app versionName must be at least phase17")

    strings = read(STRINGS)
    for name in (
        "catalog_title",
        "catalog_tools_chip",
        "catalog_addons_chip",
        "package_title",
        "transfer_title",
        "transfer_pick_import_action",
        "transfer_create_document_action",
        "artifacts_cleanup_action",
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
    print("Phase 16-17 catalog and transfer validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
