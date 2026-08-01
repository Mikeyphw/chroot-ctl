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


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    errors: list[str] = []
    required = [
        REGISTRY,
        ROOT / "tests" / "test_android_phase14_15.py",
        ANDROID / "ui" / "chroots" / "ChrootsScreen.kt",
        ANDROID / "ui" / "MainViewModel.kt",
        ANDROID / "repository" / "BridgeRepository.kt",
        ANDROID / "model" / "UiModels.kt",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    registry = read(REGISTRY)
    for token in (
        'OperationSpec("users.list"',
        'OperationSpec("users.get"',
        'OperationSpec("users.preview"',
        'OperationSpec("users.add"',
        'OperationSpec("users.remove"',
        'OperationSpec("users.sync_uid_gid"',
        'OperationSpec("users.set_shell"',
        'OperationSpec("users.set_sudo"',
        'OperationSpec("users.set_password"',
        'OperationSpec("services.list"',
        'OperationSpec("services.get"',
        'OperationSpec("services.journal"',
        'OperationSpec("services.preview"',
        'OperationSpec("services.start"',
        'OperationSpec("services.stop"',
        'OperationSpec("services.restart"',
        'OperationSpec("services.enable"',
        'OperationSpec("services.disable"',
    ):
        if token not in registry:
            errors.append(f"missing bridge operation token: {token}")
    for token in ("CONFIRMATION_REQUIRED", "PASSWORD_CONFIRMATION_MISMATCH", "deleteHome", "fixOwnership"):
        if token not in registry:
            errors.append(f"missing users/services safety token: {token}")

    app_text = "\n".join(read(path) for path in ANDROID.rglob("*.kt"))
    for token in (
        "UsersPanel",
        "UserRow",
        "ServicesPanel",
        "ServiceRow",
        "UsersPane",
        "ServicesPane",
        "previewUserAction",
        "previewServiceAction",
        "refreshUsers",
        "refreshServices",
        "users.set_password",
        "users.remove",
        "services.restart",
        "services.disable",
        "services.journal",
    ):
        if token not in app_text:
            errors.append(f"missing Android users/services token: {token}")
    forbidden = ("WebView", "runShell(", "executeArbitraryCommand", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES")
    combined = app_text + read(MANIFEST)
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
    if "versionName = \"0.1.0-phase15\"" not in build and "versionName = \"0.1.0-phase17\"" not in build and "versionName = \"0.1.0-phase19\"" not in build and "versionName = \"0.1.0-phase21\"" not in build:
        errors.append("Android app versionName must be at least phase15")

    strings = read(STRINGS)
    for name in (
        "users_actions_title",
        "action_refresh_users",
        "action_set_password",
        "action_remove_user",
        "services_actions_title",
        "action_refresh_services",
        "action_service_journal",
        "action_service_restart",
        "action_service_disable",
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
    print("Phase 14-15 users and services validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
