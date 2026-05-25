from __future__ import annotations

import logging
import os
import subprocess

import pytest

from chrootctl.system import RunResult, SystemRunner


class CompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_merges_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_env: dict[str, str] = {}

    def fake_run(args, **kwargs):
        nonlocal captured_env
        captured_env = kwargs["env"]
        return CompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("KEEP_ME", "present")
    runner = SystemRunner(logging.getLogger("test"))

    runner.run(["true"], env={"ADD_ME": "value"})

    assert captured_env["KEEP_ME"] == "present"
    assert captured_env["ADD_ME"] == "value"


def test_run_raises_with_fallback_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, **kwargs):
        return CompletedProcess(4, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SystemRunner(logging.getLogger("test"))

    with pytest.raises(RuntimeError, match="command failed: false"):
        runner.run(["false"])
