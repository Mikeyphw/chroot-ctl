from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import ChrootConfig
from .system import ProcessIdentity, capture_process_identity, process_identity_matches, terminate_process_identity


MAX_CLIPBOARD_TEXT_BYTES = 1024 * 1024
MAX_CLIPBOARD_WIRE_BYTES = 2 * 1024 * 1024


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


def _token_path(socket_path: Path) -> Path:
    return socket_path.with_name("clipboard.token")


def _identity_path(pid_file: Path) -> Path:
    return pid_file.with_name(pid_file.name + ".identity.json")


def _safe_parent(path: Path, *, mode: int = 0o700) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise RuntimeError(f"unsafe clipboard control directory: {path.parent}")
    try:
        path.parent.chmod(mode)
    except PermissionError:
        pass
    if path.is_symlink():
        raise RuntimeError(f"refusing clipboard symlink path: {path}")


def _atomic_private_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    _safe_parent(path)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
        path.chmod(mode)
    finally:
        temp.unlink(missing_ok=True)


def _read_identity(pid_file: Path) -> ProcessIdentity | None:
    path = _identity_path(pid_file)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return ProcessIdentity.from_dict(raw) if isinstance(raw, dict) else None


def daemon_status(pid_file: Path) -> dict[str, object]:
    pid = _read_pid(pid_file)
    identity = _read_identity(pid_file)
    running = pid is not None and identity is not None and identity.pid == pid and process_identity_matches(identity)
    return {"running": running, "pid": pid, "identity_verified": running}


def start_daemon(config: ChrootConfig, *, socket_path: Path | None = None, pid_file: Path | None = None, log_file: Path | None = None) -> dict[str, object]:
    defaults = default_paths(config)
    socket_path = socket_path or defaults.socket_path
    pid_file = pid_file or defaults.pid_file
    log_file = log_file or defaults.log_file
    status = daemon_status(pid_file)
    if status["running"]:
        if socket_path.exists():
            try:
                response = _socket_request(socket_path, {"action": "ping"})
                if response.get("ok") and response.get("ready"):
                    return {"started": False, "running": True, "pid": status["pid"], "socket": str(socket_path), "log_file": str(log_file)}
            except (OSError, RuntimeError, TimeoutError, ValueError):
                pass
        # A verified daemon with a missing/unresponsive socket is not stale
        # control data. Terminate that exact process identity before replacing
        # its PID files, otherwise a second daemon would orphan the first.
        stale_identity = _read_identity(pid_file)
        if stale_identity is None or not process_identity_matches(stale_identity):
            raise RuntimeError("clipboard daemon control state changed during restart")
        terminate_process_identity(stale_identity, grace_seconds=2.0)
        if process_identity_matches(stale_identity):
            raise RuntimeError("verified clipboard daemon could not be terminated; refusing to start a duplicate")
        pid_file.unlink(missing_ok=True)
        _identity_path(pid_file).unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)
    # Runtime socket/token are intentionally owned by the Termux app UID so the
    # demoted daemon and UID-synchronised chroot user can use them.  PID/identity
    # controls stay root-owned and are written only by this launcher.
    termux_stat = config.termux_home.stat()
    for path in (pid_file, log_file, _identity_path(pid_file)):
        _safe_parent(path)
    _safe_parent(socket_path)
    runtime_dir = socket_path.parent
    try:
        os.chown(runtime_dir, termux_stat.st_uid, termux_stat.st_gid)
        runtime_dir.chmod(0o700)
    except PermissionError as exc:
        raise RuntimeError(f"cannot secure clipboard runtime directory {runtime_dir}") from exc
    for stale in (pid_file, _identity_path(pid_file)):
        stale.unlink(missing_ok=True)
    token = os.urandom(32).hex()
    token_path = _token_path(socket_path)
    _atomic_private_text(token_path, token)
    os.chown(token_path, termux_stat.st_uid, termux_stat.st_gid)
    token_path.chmod(0o600)
    host_env = _termux_host_env(config)
    log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(log_fd, "a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [sys.executable, "-m", "chrootctl.cli", "clipboard", "daemon", "run", "--socket", str(socket_path), "--pid-file", str(pid_file)],
            stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ.copy(), **host_env}, text=True,
            user=termux_stat.st_uid, group=termux_stat.st_gid, extra_groups=(),
        )
    identity = capture_process_identity(process.pid)
    if identity is None or identity.start_time_ticks is None or not identity.boot_id:
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        raise RuntimeError("clipboard daemon started without a verifiable process identity")
    _atomic_private_text(pid_file, f"{process.pid}\n")
    _atomic_private_text(_identity_path(pid_file), json.dumps(identity.to_dict(), sort_keys=True) + "\n")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if socket_path.exists():
            try:
                response = _socket_request(socket_path, {"action": "ping"}, token=token)
                if response.get("ok") and response.get("ready"):
                    return {"started": True, "running": True, "pid": process.pid, "socket": str(socket_path), "log_file": str(log_file), "uid": termux_stat.st_uid, "gid": termux_stat.st_gid}
            except (OSError, RuntimeError, TimeoutError):
                pass
        time.sleep(0.05)
    terminate_process_identity(identity, grace_seconds=2.0)
    pid_file.unlink(missing_ok=True)
    _identity_path(pid_file).unlink(missing_ok=True)
    socket_path.unlink(missing_ok=True)
    raise RuntimeError("clipboard daemon did not become ready within 5 seconds")


def stop_daemon(pid_file: Path) -> dict[str, object]:
    pid = _read_pid(pid_file)
    identity = _read_identity(pid_file)
    if pid is None or identity is None or identity.pid != pid or not process_identity_matches(identity):
        pid_file.unlink(missing_ok=True); _identity_path(pid_file).unlink(missing_ok=True)
        return {"stopped": False, "running": False, "pid": pid, "identity_verified": False}
    stopped = terminate_process_identity(identity, grace_seconds=2.0)
    still_running = process_identity_matches(identity)
    if not still_running:
        pid_file.unlink(missing_ok=True)
        _identity_path(pid_file).unlink(missing_ok=True)
    return {"stopped": bool(stopped and not still_running), "running": still_running, "pid": pid, "identity_verified": True}


def run_daemon(config: ChrootConfig, *, socket_path: Path, pid_file: Path) -> None:
    token_path = _token_path(socket_path)
    # The root launcher owns pid_file/identity.  The demoted daemon touches only
    # its Termux-owned runtime socket and token.
    _safe_parent(socket_path); _safe_parent(token_path)
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("clipboard authentication token is missing or invalid")
    if socket_path.exists() or socket_path.is_symlink():
        if socket_path.is_symlink() or not stat_is_socket(socket_path):
            raise RuntimeError(f"refusing non-socket clipboard path: {socket_path}")
        socket_path.unlink()
    identity = capture_process_identity(os.getpid())
    if identity is None or identity.start_time_ticks is None or not identity.boot_id:
        raise RuntimeError("cannot capture clipboard daemon process identity")
    if _can_register_signals():
        signal.signal(signal.SIGTERM, _handle_exit_signal); signal.signal(signal.SIGINT, _handle_exit_signal)
    termux_uid = config.termux_home.stat().st_uid
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server, ThreadPoolExecutor(max_workers=8, thread_name_prefix="chrootctl-clipboard") as pool:
        server.bind(str(socket_path)); os.chmod(socket_path, 0o600); server.listen(16); server.settimeout(1.0)
        while True:
            try: conn, _ = server.accept()
            except socket.timeout: continue
            conn.settimeout(5.0)
            pool.submit(_serve_connection, config, conn, token, termux_uid)


def _serve_connection(config: ChrootConfig, conn: socket.socket, token: str, termux_uid: int) -> None:
    with conn:
        try:
            peer_uid = _peer_uid(conn)
            if peer_uid not in {0, termux_uid}:
                raise PermissionError(f"clipboard peer uid {peer_uid} is not authorized")
            request = _read_json_request(conn)
            if not _constant_time_equal(str(request.pop("token", "")), token):
                raise PermissionError("clipboard authentication failed")
            response = _handle_request(config, request)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        try: conn.sendall(json.dumps(response).encode("utf-8"))
        except OSError: return


def socket_set(socket_path: Path, text: str) -> dict[str, object]:
    return _socket_request(socket_path, {"action": "set", "text": text})


def socket_get(socket_path: Path) -> dict[str, object]:
    return _socket_request(socket_path, {"action": "get"})


def _socket_request(socket_path: Path, payload: dict[str, object], *, token: str | None = None) -> dict[str, object]:
    if token is None:
        token = _token_path(socket_path).read_text(encoding="utf-8").strip()
    wire = dict(payload); wire["token"] = token
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5.0); client.connect(str(socket_path)); client.sendall(json.dumps(wire).encode("utf-8")); client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []; total = 0
        while True:
            chunk = client.recv(65536)
            if not chunk: break
            total += len(chunk)
            if total > MAX_CLIPBOARD_WIRE_BYTES: raise RuntimeError("clipboard response exceeds wire limit")
            chunks.append(chunk)
    response = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(response, dict): raise RuntimeError("clipboard daemon returned an invalid response")
    return response


def _read_json_request(conn: socket.socket) -> dict[str, object]:
    chunks: list[bytes] = []; total = 0
    while True:
        chunk = conn.recv(65536)
        if not chunk: break
        total += len(chunk)
        if total > MAX_CLIPBOARD_WIRE_BYTES: raise RuntimeError("clipboard request exceeds wire limit")
        chunks.append(chunk)
    payload = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(payload, dict): raise RuntimeError("clipboard request must be a JSON object")
    return payload


def _handle_request(config: ChrootConfig, request: dict[str, object]) -> dict[str, object]:
    action = str(request.get("action", "")).strip().lower()
    if action == "ping": return {"ok": True, "ready": True}
    if action == "set":
        text = str(request.get("text", ""))
        if len(text.encode("utf-8")) > MAX_CLIPBOARD_TEXT_BYTES:
            raise RuntimeError("clipboard text exceeds 1 MiB")
        _termux_clipboard_set(config, text)
        return {"ok": True}
    if action == "get":
        text = _termux_clipboard_get(config)
        if len(text.encode("utf-8")) > MAX_CLIPBOARD_TEXT_BYTES:
            raise RuntimeError("clipboard text exceeds 1 MiB")
        return {"ok": True, "text": text}
    raise RuntimeError(f"unsupported clipboard action: {action}")


def _termux_clipboard_set(config: ChrootConfig, text: str) -> None:
    command = config.termux_prefix / "bin" / "termux-clipboard-set"
    if not command.exists(): raise RuntimeError(f"missing Termux clipboard command: {command}")
    _run_as_termux_user(config, [str(command)], input_text=text)


def _termux_clipboard_get(config: ChrootConfig) -> str:
    command = config.termux_prefix / "bin" / "termux-clipboard-get"
    if not command.exists(): raise RuntimeError(f"missing Termux clipboard command: {command}")
    return _run_as_termux_user(config, [str(command)], capture_output=True).stdout


def _run_as_termux_user(config: ChrootConfig, args: list[str], *, input_text: str | None = None, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    termux_stat = config.termux_home.stat(); host_env = _termux_host_env(config)
    privilege_args: dict[str, object] = {}
    if os.geteuid() == 0:
        privilege_args = {"user": termux_stat.st_uid, "group": termux_stat.st_gid, "extra_groups": ()}
    elif os.geteuid() != termux_stat.st_uid:
        raise PermissionError(f"clipboard bridge must run as root or Termux uid {termux_stat.st_uid}")
    try:
        return subprocess.run(
            args, check=True, input=input_text, text=True, capture_output=capture_output,
            env={**os.environ.copy(), **host_env}, timeout=5.0, **privilege_args,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Termux clipboard command timed out after 5 seconds: {args[0]}") from exc


def _termux_host_env(config: ChrootConfig) -> dict[str, str]:
    termux_bin = config.termux_prefix / "bin"
    return {"HOME": str(config.termux_home), "PREFIX": str(config.termux_prefix), "TMPDIR": str(config.termux_prefix / "tmp"), "PATH": f"{termux_bin}:/system/bin:/system/xbin:/vendor/bin", "LD_LIBRARY_PATH": str(config.termux_prefix / "lib")}


def _read_pid(pid_file: Path) -> int | None:
    try: return int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError): return None



def _peer_uid(conn: socket.socket) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise RuntimeError("SO_PEERCRED is required for clipboard peer authentication")
    import struct
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", raw)
    return int(uid)


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def stat_is_socket(path: Path) -> bool:
    import stat
    try: return stat.S_ISSOCK(path.lstat().st_mode)
    except FileNotFoundError: return False


def _can_register_signals() -> bool:
    try: return threading.current_thread() is threading.main_thread()
    except Exception: return False


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
        "chrootctl-xsel": config.chroot_base / "usr" / "local" / "bin" / "chrootctl-xsel",
        "chrootctl-xclip": config.chroot_base / "usr" / "local" / "bin" / "chrootctl-xclip",
    }
    wrapper_state = {name: path.exists() for name, path in wrappers.items()}
    wrappers_ready = all(wrapper_state.values())
    auto_adapt_needed = False
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
