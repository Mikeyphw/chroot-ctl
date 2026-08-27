#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from chrootctl.native_runtime import validate_native_runtime_artifact
from chrootctl.release_parity import check_release_parity


def main() -> int:
    parser = argparse.ArgumentParser(description="Final native runtime release seal check.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()

    parity = check_release_parity(args.repo_root)
    parity.require_ok()

    checks = ["android-module-parity"]
    if args.runtime is not None:
        validate_native_runtime_artifact(args.runtime)
        checks.append("native-runtime-integrity")

    print(json.dumps({"ok": True, "checks": checks}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
