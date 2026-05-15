from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
import logging

from .config import ChrootConfig
from .models import OperationResult
from .system import SystemRunner

@dataclass(frozen=True, slots=True)
class MountSpec:
    source: str
    target: Path
    fstype: str | None = None
    options: tuple[str, ...] = ()
    bind: bool = False

class ChrootController:
    def __init__(self, config: ChrootConfig, runner: SystemRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger

    def _resolved_shell(self) -> str:
        shell_exists = (self.config.chroot_base / self.config.shell_path.lstrip("/")).exists()
        bash_exists = (self.config.chroot_base / "bin/bash").exists()
        return self.config.resolved_shell(
            {self.config.shell_path: shell_exists, "/bin/bash": bash_exists}
        )

    def _is_mounted(self, source: str, target: Path, mount_table: set[tuple[str, str]] | None = None) -> bool:
        mounts = mount_table if mount_table is not None else self.runner.mount_table()
        return (source, str(target)) in mounts or any(dst == str(target) for _, dst in mounts)

    def _mount_specs(self) -> list[MountSpec]:
        return [
            MountSpec("/dev", self.config.chroot_base / "dev", bind=True),
            MountSpec("/sys", self.config.chroot_base / "sys", bind=True),
            MountSpec("/proc", self.config.chroot_base / "proc", bind=True),
            MountSpec("devpts", self.config.chroot_base / "dev/pts", fstype="devpts"),
            MountSpec("tmpfs", self.config.chroot_base / "dev/shm", fstype="tmpfs", options=(f"size={self.config.dev_shm_size}",)),
            MountSpec("/sdcard", self.config.chroot_base / "sdcard", bind=True),
            MountSpec(str(self.config.termux_prefix / "tmp"), self.config.chroot_base / "tmp", bind=True),
            MountSpec(str(self.config.termux_home), self.config.termux_home_in_chroot, bind=True),
        ]

    def _ensure_dirs(self) -> None:
        required = [
            self.config.chroot_base / "dev",
            self.config.chroot_base / "dev/pts",
            self.config.chroot_base / "dev/shm",
            self.config.chroot_base / "sys",
            self.config.chroot_base / "proc",
            self.config.chroot_base / "tmp",
            self.config.chroot_base / "sdcard",
            self.config.termux_home_in_chroot,
            self.config.user_home_in_chroot,
        ]
        for path in required:
            if not self.runner.dry_run:
                path.mkdir(parents=True, exist_ok=True)

    def mount(self) -> OperationResult:
        self.runner.require_root()
        self._ensure_dirs()
        result = OperationResult()
        mounts = self.runner.mount_table()
        self.runner.run(["busybox", "mount", "-o", "remount,dev,suid", "/data"], check=False)
        for spec in self._mount_specs():
            if self._is_mounted(spec.source, spec.target, mounts):
                result.add_skipped()
                continue
            try:
                if spec.bind:
                    self.runner.run(["busybox", "mount", "--bind", spec.source, str(spec.target)])
                else:
                    cmd = ["busybox", "mount", "-t", spec.fstype or ""]
                    if spec.options:
                        cmd += ["-o", ",".join(spec.options)]
                    cmd += [spec.source, str(spec.target)]
                    self.runner.run(cmd)
                result.add_success()
            except Exception as exc:
                result.add_failure(str(exc))
                break
        return result

    def ensure_device_nodes(self) -> OperationResult:
        self.runner.require_root()
        result = OperationResult()
        dev_dir = self.config.chroot_base / "dev"
        if not self.runner.dry_run:
            dev_dir.mkdir(parents=True, exist_ok=True)
        nodes = {
            "tty": ("5", "0", "666"),
            "console": ("5", "1", "600"),
            "null": ("1", "3", "666"),
            "zero": ("1", "5", "666"),
            "random": ("1", "8", "644"),
            "urandom": ("1", "9", "644"),
        }
        for name, (major, minor, mode) in nodes.items():
            target = dev_dir / name
            if target.exists():
                result.add_skipped()
                continue
            try:
                self.runner.run(["busybox", "mknod", "-m", mode, str(target), "c", major, minor])
                result.add_success()
            except Exception as exc:
                result.add_failure(str(exc))
        return result

    def bind_host_devices(self) -> OperationResult:
        self.runner.require_root()
        result = OperationResult()
        for name in ("tty", "console", "null", "random", "urandom"):
            source = Path("/dev") / name
            target = self.config.chroot_base / "dev" / name
            if not source.exists():
                result.add_skipped()
                continue
            try:
                self.runner.run(["busybox", "mount", "--bind", str(source), str(target)], check=False)
                result.add_success()
            except Exception as exc:
                result.add_failure(str(exc))
        return result

    def fix_tty(self) -> OperationResult:
        a = self.ensure_device_nodes()
        b = self.bind_host_devices()
        return OperationResult(
            success=a.success + b.success,
            failed=a.failed + b.failed,
            skipped=a.skipped + b.skipped,
            errors=a.errors + b.errors,
        )

    def status(self) -> list[dict[str, str]]:
        rows = []
        mounts = self.runner.mount_table()
        for spec in self._mount_specs():
            rows.append({
                "source": spec.source,
                "target": str(spec.target),
                "type": "bind" if spec.bind else (spec.fstype or ""),
                "mounted": "yes" if self._is_mounted(spec.source, spec.target, mounts) else "no",
            })
        return rows

    def start(
        self,
        *,
        login: bool,
        root_login: bool,
        exec_command: str | None,
        command_argv: list[str] | None,
    ) -> int:
        self.runner.require_root()
        if not any([login, root_login, exec_command, command_argv]):
            raise ValueError("no execution mode specified")
        self.mount()
        self.fix_tty()
        exec_user = "root" if root_login else self.config.username
        command = exec_command or self._resolved_shell()
        if command_argv:
            command = shlex.join(command_argv)
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root" if root_login else f"/home/{self.config.username}",
            "USER": exec_user,
            "SHELL": self._resolved_shell(),
            "TERM": "xterm-256color",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        result = self.runner.run(
            ["chroot", str(self.config.chroot_base), "/bin/su", "-", exec_user, "-c", command],
            check=False,
            env=env,
            capture_output=False,
        )
        return result.returncode
