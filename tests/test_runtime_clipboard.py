from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from chrootctl.runtime import clipboard


def test_handle_clipboard_doctor_reports_auto_adapt(monkeypatch, tmp_path: Path) -> None:
    config = SimpleNamespace(distro_name="ubuntu")
    registry = SimpleNamespace(get=lambda name: {"installed": True, "metadata": {}})
    context = SimpleNamespace(
        args=argparse.Namespace(clipboard_command="doctor", socket=None, pid_file=None),
        config=config,
        registry=registry,
    )
    rendered: list[str] = []

    monkeypatch.setattr(clipboard, "default_paths", lambda config: SimpleNamespace(socket_path=tmp_path / "clipboard.sock", pid_file=tmp_path / "clipboard.pid", log_file=tmp_path / "clipboard.log"))
    monkeypatch.setattr(
        clipboard,
        "clipboard_doctor",
        lambda config, **kwargs: {
            "termux_clipboard_set": True,
            "termux_clipboard_get": True,
            "termux_api_package": True,
            "daemon_running": True,
            "daemon_pid": 123,
            "daemon_termux_user": True,
            "socket_path": str(tmp_path / "clipboard.sock"),
            "socket_exists": True,
            "chroot_socket_path": "/tmp/chrootctl/clipboard.sock",
            "wrappers": {"termux-clip": False, "xsel": False, "xclip": False},
            "wrappers_ready": False,
            "setup_clipboard_registered": False,
            "auto_adapt_needed": True,
        },
    )
    monkeypatch.setattr(clipboard.console, "print", lambda message: rendered.append(str(message)))

    clipboard.handle_clipboard(context)

    assert any("AUTO" in line for line in rendered)
    assert any("termux-clipboard-set" in line for line in rendered)
    assert any("daemon runs as Termux user" in line for line in rendered)
