from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import threading
import uuid
from pathlib import Path

from chrootctl.config import ChrootConfig
from chrootctl.host_clipboard import chroot_socket_path, clipboard_doctor, default_paths, run_daemon, socket_get, socket_set, start_daemon
from chrootctl.system import ProcessIdentity


def _short_unix_socket_path() -> Path:
    # Linux/Android AF_UNIX pathname sockets have a small sockaddr_un path
    # limit (typically 108 bytes). Devtool/pytest temporary roots can exceed
    # that before the socket basename is added, especially under Termux.
    name = f"chrootctl-clip-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    candidates: list[Path] = []
    prefix = os.environ.get("PREFIX")
    if prefix:
        candidates.append(Path(prefix) / "tmp")
    candidates.extend((Path(tempfile.gettempdir()), Path("/tmp")))
    seen: set[Path] = set()
    for base in candidates:
        if base in seen:
            continue
        seen.add(base)
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        path = base / name
        if os.access(base, os.W_OK) and len(os.fsencode(path)) < 100:
            return path
    raise RuntimeError("no AF_UNIX-safe temporary directory is available")


def test_default_paths_use_termux_tmp_and_chroot_visible_socket(tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu")
    paths = default_paths(config)

    assert paths.socket_path == config.termux_prefix / "tmp" / "chrootctl" / "clipboard.sock"
    assert chroot_socket_path() == "/tmp/chrootctl/clipboard.sock"
    assert paths.pid_file.name == "clipboard-daemon.pid"


def test_socket_set_and_get_round_trip(monkeypatch, tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu")
    socket_path = _short_unix_socket_path()
    pid_file = tmp_path / "clipboard.pid"
    config.termux_home.mkdir(parents=True, exist_ok=True)
    token_path = socket_path.with_name("clipboard.token")
    socket_path.unlink(missing_ok=True)
    token_path.unlink(missing_ok=True)
    token_path.write_text("a" * 64, encoding="utf-8")
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
    # run_daemon is the demoted worker; the root launcher owns PID/identity state.
    assert not pid_file.exists()

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
    assert payload["auto_adapt_needed"] is False


def test_start_daemon_spawns_termux_user_process(monkeypatch, tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu").with_overrides(termux_prefix=tmp_path / "termux-prefix")
    config.termux_home.mkdir(parents=True, exist_ok=True)
    (config.termux_prefix / "tmp").mkdir(parents=True, exist_ok=True)
    pid_file = tmp_path / "clipboard.pid"
    log_file = tmp_path / "clipboard.log"
    socket_path = tmp_path / "runtime" / "clipboard.sock"
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    recorded: dict[str, object] = {}

    class DummyProcess:
        pid = 4321
        def poll(self): return None
        def terminate(self): return None
        def wait(self, timeout=None): return 0
        def kill(self): return None

    def fake_popen(args, **kwargs):
        recorded["args"] = list(args)
        recorded.update(kwargs)
        socket_path.touch()
        return DummyProcess()

    identity = ProcessIdentity(pid=4321, process_group_id=4321, start_time_ticks=99, boot_id="boot-test")
    monkeypatch.setattr("chrootctl.host_clipboard.subprocess.Popen", fake_popen)
    monkeypatch.setattr("chrootctl.host_clipboard.daemon_status", lambda pid_file: {"running": False, "pid": None})
    monkeypatch.setattr("chrootctl.host_clipboard.capture_process_identity", lambda pid: identity)
    monkeypatch.setattr("chrootctl.host_clipboard._socket_request", lambda *a, **k: {"ok": True, "ready": True})

    payload = start_daemon(config, socket_path=socket_path, pid_file=pid_file, log_file=log_file)

    assert payload["started"] is True
    assert payload["pid"] == 4321
    assert pid_file.read_text(encoding="utf-8").strip() == "4321"
    assert recorded["env"]["HOME"] == str(config.termux_home)
    assert recorded["env"]["PREFIX"] == str(config.termux_prefix)
    assert recorded["start_new_session"] is True
    assert "preexec_fn" not in recorded
    assert recorded["user"] == config.termux_home.stat().st_uid
    assert recorded["group"] == config.termux_home.stat().st_gid
    assert recorded["extra_groups"] == ()


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
