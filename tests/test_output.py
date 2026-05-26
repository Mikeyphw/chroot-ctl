from __future__ import annotations

import io
import os
import shutil

from rich.console import Console

from chrootctl import cli
from chrootctl.interactive import Choice, select_one
from chrootctl.output import build_console, wrap_text


def test_termux_console_width_is_capped(monkeypatch) -> None:
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback: os.terminal_size((160, 24)))

    console = build_console()

    assert console is not None
    assert console.width == 80


def test_wrap_text_avoids_ellipsis() -> None:
    wrapped = wrap_text("averylongunbrokenvalueexample", width=12)

    assert "..." not in wrapped
    assert "\n" in wrapped


def test_render_table_wraps_long_values_without_ellipsis(monkeypatch) -> None:
    buffer = io.StringIO()
    test_console = Console(file=buffer, width=36, force_terminal=False, soft_wrap=True)
    monkeypatch.setattr(cli, "console", test_console)

    cli.render_table(
        "Example",
        [
            {
                "name": "alpha",
                "description": "this is a very long description that should wrap rather than truncate",
            }
        ],
    )

    output = buffer.getvalue()

    assert "..." not in output
    assert "very long description" in output
    assert "\n" in output


def test_result_panel_wraps_long_values_without_ellipsis(monkeypatch) -> None:
    buffer = io.StringIO()
    test_console = Console(file=buffer, width=36, force_terminal=False, soft_wrap=True)
    monkeypatch.setattr(cli, "console", test_console)

    cli.result_panel(
        "Example",
        {
            "path": "/data/local/tmp/very-long-rootfs-name-that-should-wrap",
            "status": "ready",
        },
    )

    output = buffer.getvalue()

    assert "..." not in output
    assert "very-long-rootfs-name" in output
    assert "\n" in output


def test_selection_prompt_wraps_long_choices_without_ellipsis(monkeypatch, capsys) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("os.isatty", lambda fd: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    monkeypatch.setattr("chrootctl.interactive.effective_width", lambda: 28)

    select_one(
        [
            Choice(
                "alpha",
                "very-long-choice-label-that-should-wrap",
                "a very long description that should also wrap",
            )
        ],
        prompt="Items",
    )

    output = capsys.readouterr().out

    assert "..." not in output
    assert "very-long-choice-label" in output
    assert "should also wrap" in output
    assert "\n" in output
