
from __future__ import annotations

import os

import pytest

from chrootctl.runtime.confirm import confirm_action


def test_confirm_action_fails_closed_without_tty(monkeypatch) -> None:
    monkeypatch.setattr(os, "isatty", lambda fd: False)

    with pytest.raises(RuntimeError, match="interactive terminal"):
        confirm_action("Remove chroot?")


def test_confirm_action_assume_yes_skips_without_tty(monkeypatch) -> None:
    monkeypatch.setattr(os, "isatty", lambda fd: False)

    confirm_action("Remove chroot?", assume_yes=True)


def test_confirm_action_accepts_yes(monkeypatch) -> None:
    monkeypatch.setattr(os, "isatty", lambda fd: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    confirm_action("Remove chroot?")


def test_confirm_action_rejects_non_yes(monkeypatch) -> None:
    monkeypatch.setattr(os, "isatty", lambda fd: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    with pytest.raises(RuntimeError, match="operation cancelled"):
        confirm_action("Remove chroot?")
