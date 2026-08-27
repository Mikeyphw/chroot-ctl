#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from chrootctl.native_runtime import (
    DEFAULT_NATIVE_RUNTIME_ABI,
    DEFAULT_NATIVE_RUNTIME_BUILD_ROOT,
    validate_native_runtime_artifact,
)
from chrootctl.release_parity import check_release_parity


def default_runtime_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_NATIVE_RUNTIME_BUILD_ROOT / DEFAULT_NATIVE_RUNTIME_ABI


def main() -> int:
    parser = argparse.ArgumentParser(description="Final native runtime release seal check.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime", type=Path, default=None, help="Sealed native runtime artifact directory; defaults to out/native-runtime/arm64-v8a.")
    parser.add_argument("--skip-runtime-integrity", action="store_true", help="Only check Android/module parity. Use for source-only development checks, not final release sealing.")
    args = parser.parse_args()

    repo_root = args.repo_root.expanduser().resolve()
    parity = check_release_parity(repo_root)
    parity.require_ok()

    checks = ["android-module-parity"]
    if not args.skip_runtime_integrity:
        runtime = (args.runtime or default_runtime_path(repo_root)).expanduser().resolve()
        validate_native_runtime_artifact(runtime)
        checks.append("native-runtime-integrity")

    print(json.dumps({"ok": True, "checks": checks}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
