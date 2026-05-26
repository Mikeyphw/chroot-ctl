from __future__ import annotations

import subprocess

import pytest

from chrootctl.interactive import Choice, select_many, select_one


def test_select_many_uses_fzf(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fzf" if name == "fzf" else None)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="mike\tMike\tuser\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert select_many([Choice("mike", "Mike", "user")], prompt="Users") == ["mike"]


def test_select_one_uses_numbered_tty_prompt(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("os.isatty", lambda fd: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "2")

    assert select_one([Choice("root", "root"), Choice("mike", "mike")], prompt="Users") == "mike"


def test_select_many_errors_without_fzf_or_tty(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("os.isatty", lambda fd: False)

    with pytest.raises(RuntimeError, match="interactive selection requires a tty"):
        select_many([Choice("mike", "mike")], prompt="Users")
