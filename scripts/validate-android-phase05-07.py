#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "kotlin" / "com" / "mikeyphw" / "chrootctl"
RES = ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml"

REQUIRED = [
    ANDROID / "data" / "ChrootEntities.kt",
    ANDROID / "data" / "ChrootDao.kt",
    ANDROID / "repository" / "BridgeRepository.kt",
    ANDROID / "model" / "UiModels.kt",
    ANDROID / "ui" / "AppDestination.kt",
    ANDROID / "ui" / "home" / "HomeScreen.kt",
    ANDROID / "ui" / "chroots" / "ChrootsScreen.kt",
    ANDROID / "ui" / "activity" / "ActivityScreen.kt",
    ANDROID / "ui" / "tools" / "ToolsScreen.kt",
]

FORBIDDEN = [
    "WebView",
    "runShell(",
    "executeArbitraryCommand",
    "QUERY_ALL_PACKAGES",
    "READ_EXTERNAL_STORAGE",
    "MANAGE_EXTERNAL_STORAGE",
]


def main() -> int:
    errors: list[str] = []
    for path in REQUIRED:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")
    database = (ANDROID / "data" / "ChrootCtlDatabase.kt").read_text(encoding="utf-8")
    for token in ("ChrootEntity::class", "CheckResultEntity::class", "HomeSnapshotEntity::class"):
        if token not in database:
            errors.append(f"database missing {token}")
    repository = (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
    for op in ("system.dashboard", "chroots.list", "operations.list"):
        if op not in repository:
            errors.append(f"repository does not query {op}")
    registry = (ROOT / "src" / "chrootctl" / "bridge" / "registry.py").read_text(encoding="utf-8")
    if 'OperationSpec("operations.list"' not in registry:
        errors.append("Python bridge registry does not expose operations.list")
    app = (ANDROID / "ui" / "ChrootCtlApp.kt").read_text(encoding="utf-8")
    if "FoundationScreen" in app:
        errors.append("placeholder FoundationScreen is still wired into app shell")
    if "targetSdk = 36" not in (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8"):
        errors.append("targetSdk must remain 36")
    strings = RES.read_text(encoding="utf-8")
    for name in ("home_readiness_title", "chroots_empty_title", "activity_empty_title", "tools_empty_title"):
        if f'name="{name}"' not in strings:
            errors.append(f"missing string resource: {name}")
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in ANDROID.rglob("*.kt"))
    text += (ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    for token in FORBIDDEN:
        if token in text:
            errors.append(f"forbidden Android surface token found: {token}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 05-07 Android read-only foundation validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
