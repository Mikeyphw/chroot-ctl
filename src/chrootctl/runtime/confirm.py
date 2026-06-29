
from __future__ import annotations

import os


def confirm_action(prompt: str, *, assume_yes: bool = False, non_interactive: bool = False) -> None:
    if assume_yes:
        return
    if non_interactive:
        raise RuntimeError("confirmation required in non-interactive mode; rerun with --yes")
    if not _interactive_tty():
        return
    reply = input(f"{prompt} [y/N]: ").strip().lower()
    if reply not in {"y", "yes"}:
        raise RuntimeError("operation cancelled")


def _interactive_tty() -> bool:
    return os.isatty(0) and os.isatty(1)
