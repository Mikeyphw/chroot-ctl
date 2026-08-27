#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path

from chrootctl.native_runtime import (
    DEFAULT_NATIVE_RUNTIME_BUILD_ROOT,
    build_native_android_runtime,
    native_onefile_experiment_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the self-contained chrootctl Android runtime with Nuitka.")
    parser.add_argument("--output-root", type=Path, default=None, help="Output root; defaults to out/native-runtime.")
    parser.add_argument("--jobs", type=int, default=2, help="Nuitka/SCons worker count.")
    parser.add_argument("--onefile-experiment", action="store_true", help="Use the experimental Nuitka onefile command instead of the supported standalone build.")
    parser.add_argument("--allow-onefile-experiment", action="store_true", help="Actually run the experimental onefile build; otherwise it is refused unless --print-command is used.")
    parser.add_argument("--print-command", action="store_true", help="Print the build command instead of executing it.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    if args.onefile_experiment:
        plan = native_onefile_experiment_plan(repo_root, output_root=args.output_root, jobs=args.jobs)
        if args.print_command:
            print(shlex.join(plan.command))
            return 0
        if not args.allow_onefile_experiment:
            raise SystemExit(plan.warning + " Pass --allow-onefile-experiment to run it anyway.")
        plan.output_root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(plan.command, cwd=repo_root, check=False)
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)
        print(plan.output_binary)
        return 0

    output_root = args.output_root or (repo_root / DEFAULT_NATIVE_RUNTIME_BUILD_ROOT)
    if args.print_command:
        from chrootctl.native_runtime import nuitka_command

        print(shlex.join(nuitka_command(repo_root=repo_root, output_dir=output_root, jobs=args.jobs)))
        return 0
    result = build_native_android_runtime(repo_root, output_root=output_root, jobs=args.jobs)
    print(result.artifact_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
