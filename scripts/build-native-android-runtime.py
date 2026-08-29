#!/usr/bin/env python3
"""Deprecated compatibility shim. GO15 moved native-runtime builds to cmd/repoctl."""
from __future__ import annotations
import argparse, os, subprocess
from pathlib import Path

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-root", default="out/native-runtime")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--print-command", action="store_true")
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    cmd=["go","run","./cmd/repoctl","build-runtime","--output-root",str(args.output_root),"--jobs",str(args.jobs)]
    if args.print_command:
        print(" ".join(cmd)); return 0
    return subprocess.call(cmd,cwd=root,env=os.environ.copy())
if __name__ == "__main__": raise SystemExit(main())
