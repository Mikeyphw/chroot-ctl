from __future__ import annotations

import os
import shutil
import textwrap
from typing import Any

try:
    from rich.console import Console
except Exception:  # pragma: no cover
    Console = None

TERMUX_WIDTH_CAP = 80
MIN_WIDTH = 20


def is_termux() -> bool:
    prefix = os.environ.get("PREFIX", "")
    return "com.termux" in prefix or prefix.endswith("/usr")


def terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except OSError:
        return default


def effective_width(default: int = 80, width: int | None = None) -> int:
    width = terminal_width(default) if width is None else width
    if is_termux():
        width = min(width, TERMUX_WIDTH_CAP)
    return max(width, MIN_WIDTH)


def build_console(*, plain: bool = False, width: int | None = None) -> Any:
    if Console is None:
        return None
    return Console(
        force_terminal=not plain,
        no_color=plain,
        width=effective_width(width=width),
        soft_wrap=True,
    )


def wrap_text(text: str, *, width: int, initial_indent: str = "", subsequent_indent: str = "") -> str:
    if not text:
        return ""
    usable_width = max(width, MIN_WIDTH)
    return textwrap.fill(
        text,
        width=usable_width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=True,
        break_on_hyphens=False,
    )
