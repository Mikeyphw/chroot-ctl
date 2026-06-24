from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

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


def test_run_filters_termux_variables_for_chroot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_env: dict[str, str] = {}

    def fake_run(args, **kwargs):
        nonlocal captured_env
        captured_env = kwargs["env"]
        return CompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("LD_PRELOAD", "/data/data/com.termux/files/usr/lib/libtermux-exec.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/data/data/com.termux/files/usr/lib")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setenv("TMPDIR", "/data/data/com.termux/files/usr/tmp")
    monkeypatch.setenv("KEEP_ME", "present")
    runner = SystemRunner(logging.getLogger("test"))

    runner.run(["busybox", "chroot", "/tmp/rootfs", "/bin/bash"], chroot_env=True)

    assert "LD_PRELOAD" not in captured_env
    assert "LD_LIBRARY_PATH" not in captured_env
    assert "PREFIX" not in captured_env
    assert captured_env["KEEP_ME"] == "present"
    assert captured_env["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    assert captured_env["HOME"] == "/root"
    assert captured_env["USER"] == "root"
    assert captured_env["SHELL"] == "/bin/bash"
    assert captured_env["LANG"] == "C.UTF-8"
    assert captured_env["LC_ALL"] == "C.UTF-8"
    assert captured_env["TMPDIR"] == "/tmp"
    assert captured_env["TMP"] == "/tmp"
    assert captured_env["TEMP"] == "/tmp"
    assert captured_env["TERM"]


def test_run_raises_with_fallback_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, **kwargs):
        return CompletedProcess(4, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SystemRunner(logging.getLogger("test"))

    with pytest.raises(RuntimeError, match="command failed: false"):
        runner.run(["false"])


def test_run_passes_input_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_input = None

    def fake_run(args, **kwargs):
        nonlocal captured_input
        captured_input = kwargs["input"]
        return CompletedProcess(0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SystemRunner(logging.getLogger("test"))

    result = runner.run(["python3", "-"], input_text="print('ok')")

    assert captured_input == "print('ok')"
    assert result.stdout == "ok"


def test_can_execute_foreign_arch_requires_qemu_and_binfmt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = SystemRunner(logging.getLogger("test"))
    binfmt_root = tmp_path / "binfmt_misc"
    binfmt_root.mkdir()
    (binfmt_root / "status").write_text("enabled\n", encoding="utf-8")
    (binfmt_root / "qemu-arm64").write_text("enabled\n", encoding="utf-8")

    monkeypatch.setattr("chrootctl.system.shutil.which", lambda command: f"/usr/bin/{command}" if command == "qemu-arm64-static" else None)

    def fake_path(value: str):
        if value == "/proc/sys/fs/binfmt_misc":
            return binfmt_root
        return Path(value)

    monkeypatch.setattr("chrootctl.system.Path", fake_path)
    assert runner.can_execute_foreign_arch("arm64") is True


def test_can_execute_foreign_arch_returns_false_without_qemu(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = SystemRunner(logging.getLogger("test"))
    monkeypatch.setattr("chrootctl.system.shutil.which", lambda command: None)
    assert runner.can_execute_foreign_arch("arm64") is False
