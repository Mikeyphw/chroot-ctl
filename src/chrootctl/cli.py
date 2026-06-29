from __future__ import annotations

import argparse

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
    parser = build_parser()
    args = parser.parse_args()
    cli_runtime.execute_cli(
        args,
        prog=parser.prog,
        apply_start_name_shorthand_fn=apply_start_name_shorthand,
    )


if __name__ == "__main__":
    main()
