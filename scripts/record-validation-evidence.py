#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deprecated Overlay 11 evidence-recorder shim. Successful evidence is "
            "assembled and persisted only inside scripts/final-release-seal.py after "
            "that process executes every required gate."
        )
    )
    parser.add_argument(
        "--output",
        action="append",
        default=[],
        help="Rejected for direct use; run validate-final-release-seal.sh instead.",
    )
    return parser.parse_args()


def main() -> int:
    parse_args()
    print(
        "refusing direct evidence recording: run scripts/validate-final-release-seal.sh so every required gate is executed/proven first",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
