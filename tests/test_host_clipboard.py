from __future__ import annotations

import json
import logging
import socket
import threading
from pathlib import Path

from chrootctl.config import ChrootConfig
from chrootctl.host_clipboard import chroot_socket_path, clipboard_doctor, daemon_status, default_paths, run_daemon, socket_get, socket_set, start_daemon


def test_default_paths_use_termux_tmp_and_chroot_visible_socket(tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu")
    paths = default_paths(config)

    assert paths.socket_path == config.termux_prefix / "tmp" / "chrootctl" / "clipboard.sock"
    assert chroot_socket_path() == "/tmp/chrootctl/clipboard.sock"
    assert paths.pid_file.name == "clipboard-daemon.pid"


def test_socket_set_and_get_round_trip(monkeypatch, tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu")
    socket_path = tmp_path / "clipboard.sock"
    pid_file = tmp_path / "clipboard.pid"
    calls: list[tuple[str, str]] = []

    def fake_set(cfg, text: str) -> None:
        calls.append(("set", text))

    def fake_get(cfg) -> str:
        calls.append(("get", cfg.username))
        return "from-host"

    monkeypatch.setattr("chrootctl.host_clipboard._termux_clipboard_set", fake_set)
    monkeypatch.setattr("chrootctl.host_clipboard._termux_clipboard_get", fake_get)

    thread = threading.Thread(target=run_daemon, args=(config,), kwargs={"socket_path": socket_path, "pid_file": pid_file}, daemon=True)
    thread.start()

    for _ in range(50):
        if socket_path.exists():
            break
        import time
        time.sleep(0.02)

    assert socket_path.exists()
    assert daemon_status(pid_file)["running"] is True

    assert socket_set(socket_path, "hello") == {"ok": True}
    assert socket_get(socket_path) == {"ok": True, "text": "from-host"}
    assert calls == [("set", "hello"), ("get", config.username)]


def test_clipboard_doctor_reports_auto_adapt_for_existing_chroot(monkeypatch, tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu").with_overrides(termux_prefix=tmp_path / "termux-prefix")
    (config.termux_prefix / "bin").mkdir(parents=True, exist_ok=True)
    (config.termux_prefix / "bin" / "termux-clipboard-set").write_text("", encoding="utf-8")
    (config.termux_prefix / "bin" / "termux-clipboard-get").write_text("", encoding="utf-8")
    socket_path = config.termux_prefix / "tmp" / "chrootctl" / "clipboard.sock"
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("chrootctl.host_clipboard._android_package_installed", lambda package: True)
    monkeypatch.setattr("chrootctl.host_clipboard.daemon_status", lambda pid_file: {"running": True, "pid": 1234})

    payload = clipboard_doctor(
        config,
        registry_record={"installed": True, "metadata": {}},
    )

    assert payload["termux_clipboard_set"] is True
    assert payload["termux_clipboard_get"] is True
    assert payload["termux_api_package"] is True
    assert payload["daemon_running"] is True
    assert payload["socket_exists"] is True
    assert payload["wrappers_ready"] is False
    assert payload["auto_adapt_needed"] is True


def test_start_daemon_spawns_termux_user_process(monkeypatch, tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu").with_overrides(termux_prefix=tmp_path / "termux-prefix")
    config.termux_home.mkdir(parents=True, exist_ok=True)
    (config.termux_prefix / "tmp").mkdir(parents=True, exist_ok=True)
    pid_file = tmp_path / "clipboard.pid"
    log_file = tmp_path / "clipboard.log"
    socket_path = tmp_path / "clipboard.sock"

    recorded: dict[str, object] = {}

    class DummyProcess:
        pid = 4321

    def fake_popen(args, **kwargs):
        recorded["args"] = list(args)
        recorded["env"] = dict(kwargs["env"])
        recorded["preexec_fn"] = kwargs["preexec_fn"]
        return DummyProcess()

    monkeypatch.setattr("chrootctl.host_clipboard.subprocess.Popen", fake_popen)
    monkeypatch.setattr("chrootctl.host_clipboard.daemon_status", lambda pid_file: {"running": False, "pid": None})

    payload = start_daemon(
        config,
        socket_path=socket_path,
        pid_file=pid_file,
        log_file=log_file,
    )

    assert payload["started"] is True
    assert payload["pid"] == 4321
    assert pid_file.read_text(encoding="utf-8").strip() == "4321"
    assert recorded["env"]["HOME"] == str(config.termux_home)
    assert recorded["env"]["PREFIX"] == str(config.termux_prefix)
    assert recorded["preexec_fn"] is not None


def test_clipboard_doctor_reports_daemon_termux_user(monkeypatch, tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu").with_overrides(termux_prefix=tmp_path / "termux-prefix")
    config.termux_home.mkdir(parents=True, exist_ok=True)
    (config.termux_prefix / "bin").mkdir(parents=True, exist_ok=True)
    (config.termux_prefix / "bin" / "termux-clipboard-set").write_text("", encoding="utf-8")
    (config.termux_prefix / "bin" / "termux-clipboard-get").write_text("", encoding="utf-8")

    monkeypatch.setattr("chrootctl.host_clipboard._android_package_installed", lambda package: True)
    monkeypatch.setattr("chrootctl.host_clipboard.daemon_status", lambda pid_file: {"running": True, "pid": 1234})
    monkeypatch.setattr("chrootctl.host_clipboard._process_uid", lambda pid: config.termux_home.stat().st_uid)

    payload = clipboard_doctor(config, registry_record={"installed": True, "metadata": {"tools": "setup-clipboard"}})

    assert payload["daemon_termux_user"] is True
