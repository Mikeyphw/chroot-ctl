from __future__ import annotations

import contextvars
import logging
import os
import platform
import pwd
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, NoReturn, Sequence

CHROOT_ENV_BLOCKLIST = {
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "LD_AUDIT",
    "PYTHONPATH",
    "PREFIX",
    "TERMUX_VERSION",
    "TERMUX_APK_RELEASE",
    "ANDROID_ROOT",
    "ANDROID_DATA",
    "EXTERNAL_STORAGE",
    "TMPDIR",
    "TMP",
    "TEMP",
}

CHROOT_ENV_DEFAULTS = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "USER": "root",
    "SHELL": "/bin/bash",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TMPDIR": "/tmp",
    "TMP": "/tmp",
    "TEMP": "/tmp",
}

DEFAULT_CAPTURE_LIMIT_BYTES = 1024 * 1024
_POLL_SECONDS = 0.10
_TERMINATE_GRACE_SECONDS = 2.0


def qemu_user_binary_names(arch: str) -> tuple[str, ...]:
    aliases = {
        "arm64": ("qemu-aarch64-static", "qemu-arm64-static"),
        "amd64": ("qemu-x86_64-static", "qemu-amd64-static"),
    }
    return aliases.get(arch, (f"qemu-{arch}-static",))


@dataclass(slots=True, frozen=True)
class ProcessIdentity:
    pid: int
    process_group_id: int
    start_time_ticks: int | None
    boot_id: str | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "pid": self.pid,
            "processGroupId": self.process_group_id,
            "processStartTime": self.start_time_ticks,
            "processBootId": self.boot_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ProcessIdentity | None":
        try:
            pid = int(value.get("pid") or 0)
            pgid = int(value.get("processGroupId") or value.get("process_group_id") or 0)
        except (TypeError, ValueError):
            return None
        if pid <= 0 or pgid <= 0:
            return None
        raw_start = value.get("processStartTime", value.get("process_start_time"))
        try:
            start_time = int(raw_start) if raw_start is not None else None
        except (TypeError, ValueError):
            start_time = None
        raw_boot = value.get("processBootId", value.get("process_boot_id"))
        boot_id = str(raw_boot) if raw_boot else None
        return cls(pid=pid, process_group_id=pgid, start_time_ticks=start_time, boot_id=boot_id)


@dataclass(slots=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    pid: int | None = None
    process_group_id: int | None = None


_ProcessRegister = Callable[[ProcessIdentity], None]
_CancelCheck = Callable[[], bool]
_process_register: contextvars.ContextVar[_ProcessRegister | None] = contextvars.ContextVar(
    "chrootctl_process_register", default=None
)
_process_cancel_check: contextvars.ContextVar[_CancelCheck | None] = contextvars.ContextVar(
    "chrootctl_process_cancel_check", default=None
)


@contextmanager
def operation_process_scope(
    *,
    register: _ProcessRegister | None = None,
    cancelled: _CancelCheck | None = None,
) -> Iterator[None]:
    register_token = _process_register.set(register)
    cancel_token = _process_cancel_check.set(cancelled)
    try:
        yield
    finally:
        _process_register.reset(register_token)
        _process_cancel_check.reset(cancel_token)


def capture_process_identity(pid: int) -> ProcessIdentity | None:
    if pid <= 0:
        return None
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None
    return ProcessIdentity(
        pid=pid,
        process_group_id=pgid,
        start_time_ticks=_process_start_time_ticks(pid),
        boot_id=_boot_id(),
    )


def process_identity_matches(identity: ProcessIdentity) -> bool:
    # PID/PGID alone are reusable identifiers. Refuse to treat legacy/partial
    # records as signal-safe unless both boot identity and /proc start time are
    # available and still match.
    if (
        identity.pid <= 0
        or identity.process_group_id <= 0
        or identity.start_time_ticks is None
        or not identity.boot_id
    ):
        return False
    current = capture_process_identity(identity.pid)
    if current is None or current.start_time_ticks is None or not current.boot_id:
        return False
    return (
        current.process_group_id == identity.process_group_id
        and current.boot_id == identity.boot_id
        and current.start_time_ticks == identity.start_time_ticks
    )


def signal_process_identity(identity: ProcessIdentity, sig: int) -> bool:
    """Signal a process group only while its recorded Linux identity still matches."""
    if not process_identity_matches(identity):
        return False
    try:
        os.killpg(identity.process_group_id, sig)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def terminate_process_identity(identity: ProcessIdentity, *, grace_seconds: float = 2.0) -> bool:
    """Terminate a recorded process group without ever signalling a reused PID/PGID."""
    if not process_identity_matches(identity):
        return False
    signalled = signal_process_identity(identity, signal.SIGTERM)
    if not signalled:
        return False
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        if not process_identity_matches(identity):
            return True
        time.sleep(_POLL_SECONDS)
    if process_identity_matches(identity):
        signal_process_identity(identity, signal.SIGKILL)
    return True


class SystemRunner:
    def __init__(self, logger: logging.Logger, dry_run: bool = False) -> None:
        self.logger = logger
        self.dry_run = dry_run

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        env: dict[str, str] | None = None,
        clean_env: bool = False,
        chroot_env: bool = False,
        capture_output: bool = True,
        cwd: Path | None = None,
        input_text: str | None = None,
        uid: int | None = None,
        gid: int | None = None,
        background: bool = False,
        timeout: float | None = None,
        max_capture_bytes: int = DEFAULT_CAPTURE_LIMIT_BYTES,
    ) -> RunResult:
        self.logger.debug("run: %s", shlex.join(list(args)))
        if self.dry_run:
            return RunResult(returncode=0, stdout="", stderr="")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_capture_bytes < 0:
            raise ValueError("max_capture_bytes must not be negative")

        process_env = self._process_env(env=env, clean_env=clean_env, chroot_env=chroot_env)
        preexec_fn = self._demote_fn(uid=uid, gid=gid)
        if background:
            return self._run_background(args, process_env=process_env, cwd=cwd, preexec_fn=preexec_fn, capture_output=capture_output)

        stdout_file = tempfile.TemporaryFile(mode="w+b") if capture_output else None
        stderr_file = tempfile.TemporaryFile(mode="w+b") if capture_output else None
        stdin_stream = subprocess.PIPE if input_text is not None else subprocess.DEVNULL
        started = time.monotonic()
        timed_out = False
        cancelled = False
        identity: ProcessIdentity | None = None
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                list(args),
                env=process_env,
                stdin=stdin_stream,
                stdout=stdout_file if stdout_file is not None else None,
                stderr=stderr_file if stderr_file is not None else None,
                cwd=str(cwd) if cwd else None,
                preexec_fn=preexec_fn,
                start_new_session=True,
            )
            identity = capture_process_identity(process.pid)
            self._register_process(identity)
            if input_text is not None and process.stdin is not None:
                try:
                    process.stdin.write(input_text.encode("utf-8"))
                    process.stdin.flush()
                except BrokenPipeError:
                    pass
                finally:
                    process.stdin.close()

            while process.poll() is None:
                cancel_check = _process_cancel_check.get()
                if cancel_check is not None and cancel_check():
                    cancelled = True
                    self._terminate(process, identity)
                    break
                if timeout is not None and time.monotonic() - started >= timeout:
                    timed_out = True
                    self._terminate(process, identity)
                    break
                time.sleep(_POLL_SECONDS)
            if process.poll() is None:
                process.wait()

            stdout, stdout_truncated = _read_bounded_capture(stdout_file, max_capture_bytes)
            stderr, stderr_truncated = _read_bounded_capture(stderr_file, max_capture_bytes)
            result = RunResult(
                returncode=int(process.returncode or 0),
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
                cancelled=cancelled,
                truncated=stdout_truncated or stderr_truncated,
                pid=process.pid,
                process_group_id=identity.process_group_id if identity else None,
            )
        finally:
            if stdout_file is not None:
                stdout_file.close()
            if stderr_file is not None:
                stderr_file.close()

        if check and (result.cancelled or result.timed_out or result.returncode != 0):
            if result.cancelled:
                raise RuntimeError("command cancelled")
            if result.timed_out:
                raise RuntimeError(f"command timed out after {timeout:g}s")
            raise RuntimeError(result.stderr.strip() or f"command failed: {shlex.join(list(args))}")
        return result

    def spawn(
        self,
        args: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        clean_env: bool = False,
        chroot_env: bool = False,
        cwd: Path | None = None,
        stdout_path: Path | None = None,
        append: bool = True,
    ) -> int:
        self.logger.debug("spawn: %s", shlex.join(list(args)))
        if self.dry_run:
            return 0
        process_env = self._process_env(env=env, clean_env=clean_env, chroot_env=chroot_env)

        stdout_handle = None
        stderr_stream = subprocess.DEVNULL
        try:
            if stdout_path is not None:
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                flags = os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
                flags |= os.O_APPEND if append else os.O_TRUNC
                fd = os.open(stdout_path, flags, 0o600)
                stdout_handle = os.fdopen(fd, "a" if append else "w", encoding="utf-8")
                stderr_stream = subprocess.STDOUT
            process = subprocess.Popen(
                list(args),
                env=process_env,
                stdout=stdout_handle or subprocess.DEVNULL,
                stderr=stderr_stream,
                stdin=subprocess.DEVNULL,
                text=True,
                cwd=str(cwd) if cwd else None,
                start_new_session=True,
            )
            self._register_process(capture_process_identity(process.pid))
            return int(process.pid)
        finally:
            if stdout_handle is not None:
                stdout_handle.close()

    def exec(
        self,
        args: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        clean_env: bool = False,
        chroot_env: bool = False,
        cwd: Path | None = None,
    ) -> NoReturn:
        self.logger.debug("exec: %s", shlex.join(list(args)))
        if self.dry_run:
            raise SystemExit(0)
        process_env = self._process_env(env=env, clean_env=clean_env, chroot_env=chroot_env)
        executable = shutil.which(args[0]) or args[0]
        os.execvpe(executable, list(args), process_env)

    def require_root(self) -> None:
        if os.geteuid() != 0:
            raise PermissionError("root privileges required")

    def is_root(self) -> bool:
        return os.geteuid() == 0

    def sudo_available(self) -> bool:
        return shutil.which("sudo") is not None

    def reexec_with_sudo(self, argv: list[str]) -> int:
        if self.dry_run:
            self.logger.info("dry-run sudo re-exec: %s", shlex.join(["sudo", *argv]))
            return 0
        if not self.sudo_available():
            raise PermissionError("sudo is not available and root is required")
        completed = subprocess.run(["sudo", *argv], check=False)
        return completed.returncode

    def python_reexec_argv(self) -> list[str]:
        return [sys.executable, *sys.argv]

    def mount_table(self) -> set[tuple[str, str]]:
        mounts: set[tuple[str, str]] = set()
        try:
            with open("/proc/mounts", "r", encoding="utf-8") as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) >= 2:
                        mounts.add((parts[0], parts[1]))
        except FileNotFoundError:
            pass
        return mounts

    def host_termux_uid_gid(self, termux_home: Path) -> tuple[int, int]:
        stat = termux_home.stat()
        return stat.st_uid, stat.st_gid

    def host_arch(self) -> str:
        machine = platform.machine().lower()
        aliases = {
            "x86_64": "amd64",
            "amd64": "amd64",
            "aarch64": "arm64",
            "arm64": "arm64",
        }
        return aliases.get(machine, machine)

    def current_username(self) -> str:
        return pwd.getpwuid(os.getuid()).pw_name

    def command_exists(self, command: str) -> bool:
        return shutil.which(command) is not None

    def can_execute_foreign_arch(self, arch: str) -> bool:
        if not any(self.command_exists(candidate) for candidate in qemu_user_binary_names(arch)):
            return False
        binfmt_misc = Path("/proc/sys/fs/binfmt_misc")
        if not binfmt_misc.exists():
            return False
        status_path = binfmt_misc / "status"
        try:
            status_text = status_path.read_text(encoding="utf-8", errors="replace").strip().lower()
        except OSError:
            status_text = ""
        if status_text and status_text not in {"1", "enabled"}:
            return False
        for candidate in (f"qemu-{arch}", f"qemu-{arch}-static", arch, arch.upper()):
            entry = binfmt_misc / candidate
            if not entry.exists():
                continue
            try:
                entry_text = entry.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            if "enabled" in entry_text:
                return True
        return False

    def _process_env(
        self,
        *,
        env: dict[str, str] | None,
        clean_env: bool,
        chroot_env: bool,
    ) -> dict[str, str]:
        process_env = {} if clean_env else os.environ.copy()
        if chroot_env:
            for key in CHROOT_ENV_BLOCKLIST:
                process_env.pop(key, None)
            process_env.update(CHROOT_ENV_DEFAULTS)
            process_env["TERM"] = os.environ.get("TERM") or "xterm-256color"
        if env is not None:
            process_env.update(env)
        return process_env

    def _demote_fn(self, *, uid: int | None, gid: int | None) -> Callable[[], None] | None:
        if uid is None and gid is None:
            return None

        def _demote() -> None:
            if os.geteuid() == 0:
                os.setgroups([])
            if gid is not None:
                os.setgid(gid)
            if uid is not None:
                os.setuid(uid)

        return _demote

    def _run_background(
        self,
        args: Sequence[str],
        *,
        process_env: dict[str, str],
        cwd: Path | None,
        preexec_fn: Callable[[], None] | None,
        capture_output: bool,
    ) -> RunResult:
        stream = subprocess.DEVNULL if capture_output else None
        process = subprocess.Popen(
            list(args),
            env=process_env,
            stdout=stream,
            stderr=stream,
            stdin=subprocess.DEVNULL,
            cwd=str(cwd) if cwd else None,
            preexec_fn=preexec_fn,
            start_new_session=True,
        )
        identity = capture_process_identity(process.pid)
        self._register_process(identity)
        return RunResult(
            returncode=0,
            stdout="",
            stderr="",
            pid=process.pid,
            process_group_id=identity.process_group_id if identity else None,
        )

    def _register_process(self, identity: ProcessIdentity | None) -> None:
        register = _process_register.get()
        if identity is not None and register is not None:
            register(identity)

    def _terminate(self, process: subprocess.Popen[bytes], identity: ProcessIdentity | None) -> None:
        if identity is not None:
            signal_process_identity(identity, signal.SIGTERM)
        else:
            try:
                process.terminate()
            except ProcessLookupError:
                return
        deadline = time.monotonic() + _TERMINATE_GRACE_SECONDS
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is not None:
            return
        if identity is not None:
            if signal_process_identity(identity, signal.SIGKILL):
                return
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _read_bounded_capture(stream: BinaryIO | None, max_bytes: int) -> tuple[str, bool]:
    if stream is None:
        return "", False
    handle = stream
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    if max_bytes <= 0:
        return "", size > 0
    if size <= max_bytes:
        handle.seek(0)
        data = handle.read()
        return data.decode("utf-8", errors="replace"), False
    head_bytes = max_bytes // 2
    tail_bytes = max_bytes - head_bytes
    handle.seek(0)
    head = handle.read(head_bytes)
    handle.seek(max(0, size - tail_bytes))
    tail = handle.read(tail_bytes)
    marker = f"\n... chrootctl capture truncated {size - max_bytes} bytes ...\n".encode("utf-8")
    return (head + marker + tail).decode("utf-8", errors="replace"), True


def _process_start_time_ticks(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        remainder = raw.rsplit(")", 1)[1].strip().split()
        return int(remainder[19])
    except (OSError, IndexError, ValueError):
        return None


def _boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return value or None
