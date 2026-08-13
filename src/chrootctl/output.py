from __future__ import annotations

import json
import os
import shutil
import textwrap
from dataclasses import asdict, is_dataclass
from typing import Any

from .models import DisplayRenderable, to_display_dict

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover
    Console = None
    Panel = None
    Table = None
    Text = None

TERMUX_WIDTH_CAP = 80
MIN_WIDTH = 20
NARROW_WIDTH = 72
COMPACT_CATALOG_WIDTH = 88


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


def is_narrow_console(console: Any | None = None) -> bool:
    current_width = _console_width(build_console() if console is None else console)
    return current_width <= NARROW_WIDTH


def use_compact_catalog_layout(console: Any | None = None) -> bool:
    current_width = _console_width(build_console() if console is None else console)
    return current_width <= COMPACT_CATALOG_WIDTH


def render_table(
    title: str,
    rows: list[dict[str, Any] | DisplayRenderable],
    *,
    console: Any | None = None,
    json_output: bool = False,
) -> None:
    console = build_console(plain=json_output) if console is None else console
    if json_output:
        render_json([_json_ready(row) for row in rows], console=console)
        return
    normalized_rows = [to_display_dict(row) for row in rows]

    keys: list[str] = []
    for row in normalized_rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    if not keys:
        console.print(Panel(title, expand=False))
        return
    if is_narrow_console(console):
        _render_compact_rows(title, normalized_rows, console=console)
        return

    table = Table(title=title, box=None, expand=True, pad_edge=False, show_header=True)
    for index, key in enumerate(keys):
        table.add_column(
            key,
            overflow="fold",
            no_wrap=False,
            ratio=1 if index == 0 else 3,
        )
    for row in normalized_rows:
        table.add_row(*(str(row.get(key, "")) for key in keys))
    console.print(table)


def result_panel(
    title: str,
    data: dict[str, Any] | DisplayRenderable,
    *,
    console: Any | None = None,
    json_output: bool = False,
) -> None:
    console = build_console(plain=json_output) if console is None else console
    if json_output:
        render_json(_json_ready(data), console=console)
        return
    normalized = to_display_dict(data)

    body = Table.grid(expand=True)
    body.add_column(style="bold cyan", no_wrap=True)
    body.add_column(overflow="fold", ratio=1)
    for key, value in normalized.items():
        body.add_row(f"{key}=", str(value))
    console.print(Panel(body, title=title, expand=False))


def render_json(data: Any, *, console: Any | None = None) -> None:
    console = build_console(plain=True) if console is None else console
    console.print(json.dumps(data, indent=2, sort_keys=True))


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, DisplayRenderable):
        raw = getattr(value, "__dict__", None)
        if isinstance(raw, dict):
            return {str(key): _json_ready(item) for key, item in raw.items()}
        return to_display_dict(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_ready(value.to_dict())
    return str(value)


def _render_compact_rows(title: str, rows: list[dict[str, str]], *, console: Any) -> None:
    console.print(Panel(Text(title), title=title, expand=False))
    for index, row in enumerate(rows, start=1):
        body = Table.grid(expand=True)
        body.add_column(style="bold cyan", no_wrap=True)
        body.add_column(overflow="fold", ratio=1)
        for key, value in row.items():
            body.add_row(f"{key}=", str(value))
        console.print(Panel(body, title=_row_title(title, row, index), expand=False))


def _row_title(title: str, row: dict[str, str], index: int) -> str:
    for key in ("name", "check", "username", "target", "category", "kind"):
        value = row.get(key)
        if value:
            return f"{title} · {value}"
    return f"{title} · item {index}"


def _console_width(console: Any) -> int:
    width = getattr(console, "width", None)
    if isinstance(width, int):
        return width
    return effective_width()
