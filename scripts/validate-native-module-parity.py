#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from chrootctl.release_parity import check_release_parity


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Android app/module/native-runtime release parity.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="Print the parity report as JSON.")
    args = parser.parse_args()
    result = check_release_parity(args.repo_root)
    if args.json:
        print(json.dumps({"ok": result.ok, "checked": result.checked, "mismatches": result.mismatches}, indent=2))
    else:
        for item in result.checked:
            print(f"checked: {item}")
        if result.mismatches:
            for item in result.mismatches:
                print(f"mismatch: {item}")
    result.require_ok()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
