#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()
required = [
    "docs/android/WEBUI_PARITY_MATRIX.md",
    "docs/android/ANDROID_APP_ARCHITECTURE.md",
    "src/chrootctl/bridge/cli.py",
    "src/chrootctl/operations/manager.py",
    "android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl",
    "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt",
    "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt",
]
missing = [path for path in required if not (ROOT / path).is_file()]
if missing:
    raise SystemExit("Missing phase 0-4 files: " + ", ".join(missing))

aidl = (ROOT / required[4]).read_text(encoding="utf-8").lower()
if "runshell" in aidl or "executecommand" in aidl or "string command" in aidl:
    raise SystemExit("Unsafe arbitrary command capability found in AIDL")

config = (ROOT / ".devtool.toml").read_text(encoding="utf-8")
for token in ("[targets.chrootctl_android]", 'root = "android"', 'build = [":app:assembleDebug"]', 'lint = [":app:lintDebug"]'):
    if token not in config:
        raise SystemExit(f"Missing Devtool Android target contract: {token}")

pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
if 'chrootctl-app = "chrootctl.bridge.cli:main"' not in pyproject:
    raise SystemExit("Missing chrootctl-app console script")

print(json.dumps({"checks": 7, "status": "passed", "phase": "0-4"}, sort_keys=True))
