from __future__ import annotations

import argparse
import sys

from . import cli_runtime
from .config import ChrootConfig
from .parser import build_parser
from .registry import ChrootRegistry


def apply_start_name_shorthand(
    args: argparse.Namespace,
    config: ChrootConfig,
    registry: ChrootRegistry,
) -> ChrootConfig:
    return config


def main() -> None:
    if "app" in sys.argv[1:]:
        from .bridge.cli import main as bridge_main

        app_index = sys.argv.index("app")
        bridge_argv = [*sys.argv[1:app_index], *sys.argv[app_index + 1 :]]
        raise SystemExit(bridge_main(bridge_argv))
    parser = build_parser()
    args = parser.parse_args()
    cli_runtime.execute_cli(
        args,
        prog=parser.prog,
        apply_start_name_shorthand_fn=apply_start_name_shorthand,
    )


if __name__ == "__main__":
    main()
