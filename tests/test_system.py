from __future__ import annotations

import io
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


def _install_fake_popen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, object]:
    captured: dict[str, object] = {}

    class CapturingStdin(io.BytesIO):
        def close(self) -> None:
            captured["input"] = self.getvalue().decode("utf-8", errors="replace")
            super().close()

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            captured["args"] = list(args)
            captured.update(kwargs)
            self.pid = os.getpid()
            self.returncode = returncode
            self.stdin = CapturingStdin() if kwargs.get("stdin") == subprocess.PIPE else None
            out = kwargs.get("stdout")
            err = kwargs.get("stderr")
            if hasattr(out, "write"):
                out.write(stdout.encode("utf-8"))
                out.flush()
            if hasattr(err, "write"):
                err.write(stderr.encode("utf-8"))
                err.flush()

        def poll(self):
            return self.returncode

        def wait(self, *args, **kwargs):
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    return captured


def test_run_merges_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _install_fake_popen(monkeypatch)
    monkeypatch.setenv("KEEP_ME", "present")
    runner = SystemRunner(logging.getLogger("test"))

    runner.run(["true"], env={"ADD_ME": "value"})

    captured_env = captured["env"]
    assert isinstance(captured_env, dict)
    assert captured_env["KEEP_ME"] == "present"
    assert captured_env["ADD_ME"] == "value"


def test_run_filters_termux_variables_for_chroot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _install_fake_popen(monkeypatch)
    monkeypatch.setenv("LD_PRELOAD", "/data/data/com.termux/files/usr/lib/libtermux-exec.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/data/data/com.termux/files/usr/lib")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setenv("TMPDIR", "/data/data/com.termux/files/usr/tmp")
    monkeypatch.setenv("KEEP_ME", "present")
    runner = SystemRunner(logging.getLogger("test"))

    runner.run(["busybox", "chroot", "/tmp/rootfs", "/bin/bash"], chroot_env=True)

    captured_env = captured["env"]
    assert isinstance(captured_env, dict)
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
    _install_fake_popen(monkeypatch, returncode=4)
    runner = SystemRunner(logging.getLogger("test"))

    with pytest.raises(RuntimeError, match="command failed: false"):
        runner.run(["false"])


def test_run_passes_input_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _install_fake_popen(monkeypatch, stdout="ok")
    runner = SystemRunner(logging.getLogger("test"))

    result = runner.run(["python3", "-"], input_text="print('ok')")

    assert captured["input"] == "print('ok')"
    assert result.stdout == "ok"


def test_can_execute_foreign_arch_requires_qemu_and_binfmt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = SystemRunner(logging.getLogger("test"))
    binfmt_root = tmp_path / "binfmt_misc"
    binfmt_root.mkdir()
    (binfmt_root / "status").write_text("enabled\n", encoding="utf-8")
    (binfmt_root / "qemu-arm64").write_text("enabled\n", encoding="utf-8")

    monkeypatch.setattr("chrootctl.system.shutil.which", lambda command: f"/usr/bin/{command}" if command == "qemu-aarch64-static" else None)

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
