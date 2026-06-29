from __future__ import annotations

import os
import platform
import pwd
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Sequence
import logging

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


def qemu_user_binary_names(arch: str) -> tuple[str, ...]:
    aliases = {
        "arm64": ("qemu-aarch64-static", "qemu-arm64-static"),
        "amd64": ("qemu-x86_64-static", "qemu-amd64-static"),
    }
    return aliases.get(arch, (f"qemu-{arch}-static",))


@dataclass(slots=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str

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
    ) -> RunResult:
        self.logger.debug("run: %s", shlex.join(list(args)))
        if self.dry_run:
            return RunResult(returncode=0, stdout="", stderr="")
        process_env = {} if clean_env else os.environ.copy()
        if chroot_env:
            for key in CHROOT_ENV_BLOCKLIST:
                process_env.pop(key, None)
            process_env.update(CHROOT_ENV_DEFAULTS)
            process_env["TERM"] = os.environ.get("TERM") or "xterm-256color"
        if env is not None:
            process_env.update(env)
        preexec_fn = None
        if uid is not None or gid is not None:
            def _demote() -> None:
                if gid is not None:
                    os.setgid(gid)
                if uid is not None:
                    os.setuid(uid)
            preexec_fn = _demote

        if background:
            stdout_stream = subprocess.DEVNULL if capture_output else None
            stderr_stream = subprocess.DEVNULL if capture_output else None
            subprocess.Popen(
                list(args),
                env=process_env,
                stdout=stdout_stream,
                stderr=stderr_stream,
                stdin=subprocess.DEVNULL,
                text=True,
                cwd=str(cwd) if cwd else None,
                preexec_fn=preexec_fn,
                start_new_session=True,
            )
            result = RunResult(returncode=0, stdout="", stderr="")
        else:
            completed = subprocess.run(
                list(args),
                check=False,
                env=process_env,
                capture_output=capture_output,
                input=input_text,
                text=True,
                cwd=str(cwd) if cwd else None,
                preexec_fn=preexec_fn,
            )
            result = RunResult(
                returncode=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            )
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"command failed: {shlex.join(list(args))}")
        return result


    def exec(
        self,
        args: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        clean_env: bool = False,
        chroot_env: bool = False,
        cwd: Path | None = None,
    ) -> "NoReturn":
        self.logger.debug("exec: %s", shlex.join(list(args)))
        if self.dry_run:
            raise SystemExit(0)
        process_env = {} if clean_env else os.environ.copy()
        if chroot_env:
            for key in CHROOT_ENV_BLOCKLIST:
                process_env.pop(key, None)
            process_env.update(CHROOT_ENV_DEFAULTS)
            process_env["TERM"] = os.environ.get("TERM") or "xterm-256color"
        if env is not None:
            process_env.update(env)
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
