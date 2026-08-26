#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from chrootctl.native_runtime import DEFAULT_NATIVE_RUNTIME_BUILD_ROOT, build_native_android_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the self-contained chrootctl Android runtime with Nuitka standalone mode.")
    parser.add_argument("--output-root", type=Path, default=None, help="Output root; defaults to out/native-runtime.")
    parser.add_argument("--jobs", type=int, default=2, help="Nuitka/SCons worker count.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_root = args.output_root or (repo_root / DEFAULT_NATIVE_RUNTIME_BUILD_ROOT)
    result = build_native_android_runtime(repo_root, output_root=output_root, jobs=args.jobs)
    print(result.artifact_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
