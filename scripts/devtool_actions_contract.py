#!/usr/bin/env python3
"""Read-only EXO-bound GitHub workflow presence contract. Not a remote acceptance gate."""
from pathlib import Path
import sys
FILES = ['.github/workflows/ci.yml', '.github/workflows/devtool-chrootctl-build.yml']
root = Path(__file__).resolve().parents[1]
for name in FILES:
    p = root / name
    if not p.is_file() or p.is_symlink() or not p.read_text(encoding="utf-8").strip():
        print(f"Missing or empty CI workflow: {name}", file=sys.stderr)
        sys.exit(2)
print("CI workflow file contract: PASS (local only; GitHub execution not verified)")
