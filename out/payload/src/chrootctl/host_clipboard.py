from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import ChrootConfig


@dataclass(frozen=True, slots=True)
class ClipboardPaths:
    socket_path: Path
    pid_file: Path
    log_file: Path


def default_paths(config: ChrootConfig) -> ClipboardPaths:
    runtime_dir = config.termux_prefix / "tmp" / "chrootctl"
    control_dir = Path("/data/adb/chrootctl")
    return ClipboardPaths(
        socket_path=runtime_dir / "clipboard.sock",
        pid_file=control_dir / "clipboard-daemon.pid",
        log_file=control_dir / "clipboard-daemon.log",
    )


def chroot_socket_path() -> str:
    return "/tmp/chrootctl/clipboard.sock"


def daemon_status(pid_file: Path) -> dict[str, object]:
    pid = _read_pid(pid_file)
    running = pid is not None and _pid_is_running(pid)
    return {"running": running, "pid": pid}


def start_daemon(config: ChrootConfig, *, socket_path: Path | None = None, pid_file: Path | None = None, log_file: Path | None = None) -> dict[str, object]:
    defaults = default_paths(config)
    socket_path = socket_path or defaults.socket_path
    pid_file = pid_file or defaults.pid_file
    log_file = log_file or defaults.log_file
    status = daemon_status(pid_file)
    if status["running"]:
        return {"started": False, "running": True, "pid": status["pid"], "socket": str(socket_path), "log_file": str(log_file)}

    socket_path.parent.mkdir(parents=True, exist_ok=True)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    termux_stat = config.termux_home.stat()
    host_env = _termux_host_env(config)

    with log_file.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "chrootctl.cli",
                "clipboard",
                "daemon",
                "run",
                "--socket",
                str(socket_path),
                "--pid-file",
                str(pid_file),
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ.copy(), **host_env},
            text=True,
            preexec_fn=_preexec_demote(termux_stat.st_uid, termux_stat.st_gid),
        )
    pid_file.write_text(str(process.pid), encoding="utf-8")
    return {
        "started": True,
        "running": True,
        "pid": process.pid,
        "socket": str(socket_path),
        "log_file": str(log_file),
        "uid": termux_stat.st_uid,
        "gid": termux_stat.st_gid,
    }


def stop_daemon(pid_file: Path) -> dict[str, object]:
    pid = _read_pid(pid_file)
    if pid is None:
        return {"stopped": False, "running": False}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return {"stopped": False, "running": False, "pid": pid}
    pid_file.unlink(missing_ok=True)
    return {"stopped": True, "running": False, "pid": pid}


def run_daemon(config: ChrootConfig, *, socket_path: Path, pid_file: Path) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    _write_pid_file(pid_file, os.getpid())
    atexit.register(lambda: _cleanup_pid_file(pid_file, os.getpid()))
    atexit.register(lambda: socket_path.unlink(missing_ok=True))
    if _can_register_signals():
        signal.signal(signal.SIGTERM, _handle_exit_signal)
        signal.signal(signal.SIGINT, _handle_exit_signal)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o666)
        server.listen(8)
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    request = _read_json_request(conn)
                    response = _handle_request(config, request)
                except Exception as exc:  # pragma: no cover - defensive fallback
                    response = {"ok": False, "error": str(exc)}
                conn.sendall(json.dumps(response).encode("utf-8"))


def socket_set(socket_path: Path, text: str) -> dict[str, object]:
    return _socket_request(socket_path, {"action": "set", "text": text})


def socket_get(socket_path: Path) -> dict[str, object]:
    return _socket_request(socket_path, {"action": "get"})


def _socket_request(socket_path: Path, payload: dict[str, object]) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(json.dumps(payload).encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    response = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("clipboard daemon returned an invalid response")
    return response


def _read_json_request(conn: socket.socket) -> dict[str, object]:
    chunks: list[bytes] = []
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        if sum(len(item) for item in chunks) > 1024 * 1024:
            raise RuntimeError("clipboard request exceeds 1 MiB")
    payload = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("clipboard request must be a JSON object")
    return payload


def _handle_request(config: ChrootConfig, request: dict[str, object]) -> dict[str, object]:
    action = str(request.get("action", "")).strip().lower()
    if action == "set":
        _termux_clipboard_set(config, str(request.get("text", "")))
        return {"ok": True}
    if action == "get":
        return {"ok": True, "text": _termux_clipboard_get(config)}
    raise RuntimeError(f"unsupported clipboard action: {action}")


def _termux_clipboard_set(config: ChrootConfig, text: str) -> None:
    command = config.termux_prefix / "bin" / "termux-clipboard-set"
    if not command.exists():
        raise RuntimeError(f"missing Termux clipboard command: {command}")
    _run_as_termux_user(config, [str(command)], input_text=text)


def _termux_clipboard_get(config: ChrootConfig) -> str:
    command = config.termux_prefix / "bin" / "termux-clipboard-get"
    if not command.exists():
        raise RuntimeError(f"missing Termux clipboard command: {command}")
    completed = _run_as_termux_user(config, [str(command)], capture_output=True)
    return completed.stdout


def _run_as_termux_user(
    config: ChrootConfig,
    args: list[str],
    *,
    input_text: str | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    termux_stat = config.termux_home.stat()
    host_env = _termux_host_env(config)

    return subprocess.run(
        args,
        check=True,
        input=input_text,
        text=True,
        capture_output=capture_output,
        env={**os.environ.copy(), **host_env},
        preexec_fn=_preexec_demote(termux_stat.st_uid, termux_stat.st_gid),
    )



def _termux_host_env(config: ChrootConfig) -> dict[str, str]:
    termux_bin = config.termux_prefix / "bin"
    return {
        "HOME": str(config.termux_home),
        "PREFIX": str(config.termux_prefix),
        "TMPDIR": str(config.termux_prefix / "tmp"),
        "PATH": f"{termux_bin}:/system/bin:/system/xbin:/vendor/bin",
        "LD_LIBRARY_PATH": str(config.termux_prefix / "lib"),
    }


def _preexec_demote(uid: int, gid: int):
    def _demote() -> None:
        os.setgid(gid)
        os.setuid(uid)

    return _demote


def _write_pid_file(pid_file: Path, pid: int) -> None:
    try:
        pid_file.write_text(str(pid), encoding="utf-8")
    except PermissionError:
        return


def _cleanup_pid_file(pid_file: Path, pid: int) -> None:
    recorded = _read_pid(pid_file)
    if recorded == pid:
        pid_file.unlink(missing_ok=True)


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _can_register_signals() -> bool:
    try:
        import threading
        return threading.current_thread() is threading.main_thread()
    except Exception:
        return False


def _handle_exit_signal(signum: int, _frame) -> None:
    raise SystemExit(128 + signum)


def clipboard_doctor(config: ChrootConfig, *, pid_file: Path | None = None, socket_path: Path | None = None, registry_record: dict[str, object] | None = None) -> dict[str, object]:
    defaults = default_paths(config)
    pid_file = pid_file or defaults.pid_file
    socket_path = socket_path or defaults.socket_path
    daemon = daemon_status(pid_file)
    termux_set = config.termux_prefix / "bin" / "termux-clipboard-set"
    termux_get = config.termux_prefix / "bin" / "termux-clipboard-get"
    termux_api_package = _android_package_installed("com.termux.api")
    metadata = registry_record.get("metadata", {}) if isinstance(registry_record, dict) else {}
    applied_tools = _metadata_names(metadata.get("tools", "")) if isinstance(metadata, dict) else []
    wrappers = {
        "termux-clip": config.chroot_base / "usr" / "local" / "bin" / "termux-clip",
        "xsel": config.chroot_base / "usr" / "local" / "bin" / "xsel",
        "xclip": config.chroot_base / "usr" / "local" / "bin" / "xclip",
    }
    wrapper_state = {name: path.exists() for name, path in wrappers.items()}
    wrappers_ready = all(wrapper_state.values())
    auto_adapt_needed = bool(registry_record and bool(registry_record.get("installed")) and "setup-clipboard" not in applied_tools and not wrappers_ready)
    termux_uid = config.termux_home.stat().st_uid if config.termux_home.exists() else None
    daemon_uid = _process_uid(int(daemon["pid"])) if daemon.get("running") and daemon.get("pid") is not None else None
    return {
        "termux_clipboard_set": termux_set.exists(),
        "termux_clipboard_get": termux_get.exists(),
        "termux_api_package": termux_api_package,
        "daemon_running": bool(daemon.get("running")),
        "daemon_pid": daemon.get("pid"),
        "daemon_uid": daemon_uid,
        "daemon_termux_user": daemon_uid is not None and termux_uid is not None and daemon_uid == termux_uid,
        "socket_path": str(socket_path),
        "socket_exists": socket_path.exists(),
        "chroot_socket_path": chroot_socket_path(),
        "wrappers": wrapper_state,
        "wrappers_ready": wrappers_ready,
        "setup_clipboard_registered": "setup-clipboard" in applied_tools,
        "auto_adapt_needed": auto_adapt_needed,
    }



def _process_uid(pid: int) -> int | None:
    try:
        with Path(f"/proc/{pid}/status").open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("Uid:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1])
    except (FileNotFoundError, PermissionError, ValueError):
        return None
    return None


def _metadata_names(raw: object) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [name for name in (item.strip() for item in raw.split(",")) if name]


def _android_package_installed(package_name: str) -> bool:
    try:
        completed = subprocess.run(
            ["pm", "path", package_name],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return completed.returncode == 0 and bool(completed.stdout.strip())
