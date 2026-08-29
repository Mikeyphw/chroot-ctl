#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from chrootctl.native_runtime import DEFAULT_NATIVE_RUNTIME_BUILD_ROOT, build_native_android_runtime, go_android_build_command


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the self-contained chrootctl Android runtime as a Go native executable.")
    parser.add_argument("--output-root", type=Path, default=None, help="Output root; defaults to out/native-runtime.")
    parser.add_argument("--jobs", type=int, default=2, help="Maximum Go build CPU parallelism.")
    parser.add_argument("--print-command", action="store_true", help="Print the Go build command instead of executing it.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_root = (args.output_root or (repo_root / DEFAULT_NATIVE_RUNTIME_BUILD_ROOT)).expanduser().resolve()
    if args.print_command:
        print(shlex.join(go_android_build_command(repo_root=repo_root, output_binary=output_root / "arm64-v8a/chrootctl")))
        return 0
    result = build_native_android_runtime(repo_root, output_root=output_root, jobs=args.jobs)
    print(result.artifact_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
