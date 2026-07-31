from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from typing import NoReturn
from pathlib import Path
import logging

from .config import BindMount, ChrootConfig
from .models import OperationResult
from .system import SystemRunner

@dataclass(frozen=True, slots=True)
class MountSpec:
    source: str
    target: Path
    fstype: str | None = None
    options: tuple[str, ...] = ()
    bind: bool = False
    read_only: bool = False

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

    def _config_mount_specs(self, mounts: tuple[BindMount, ...]) -> list[MountSpec]:
        return [
            MountSpec(mount.source, self.config.chroot_base / mount.target, bind=True, read_only=mount.read_only)
            for mount in mounts
            if mount.enabled
        ]

    def _mount_specs(self) -> list[MountSpec]:
        specs = [
            MountSpec("/dev", self.config.chroot_base / "dev", bind=True),
            MountSpec("/sys", self.config.chroot_base / "sys", bind=True),
            MountSpec("/proc", self.config.chroot_base / "proc", bind=True),
            MountSpec("devpts", self.config.chroot_base / "dev/pts", fstype="devpts"),
            MountSpec("tmpfs", self.config.chroot_base / "dev/shm", fstype="tmpfs", options=(f"size={self.config.dev_shm_size}",)),
            MountSpec("/sdcard", self.config.chroot_base / "sdcard", bind=True),
            MountSpec(str(self.config.termux_prefix / "tmp"), self.config.chroot_base / "tmp", bind=True),
            MountSpec(str(self.config.termux_home), self.config.termux_home_in_chroot, bind=True),
        ]
        specs.extend(self._config_mount_specs(self.config.media_mounts))
        specs.extend(self._config_mount_specs(self.config.extra_bind_mounts))
        return specs

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
        required.extend(spec.target for spec in self._config_mount_specs(self.config.media_mounts))
        required.extend(spec.target for spec in self._config_mount_specs(self.config.extra_bind_mounts))
        for path in required:
            if not self.runner.dry_run:
                path.mkdir(parents=True, exist_ok=True)

    def _session_env(self, *, root: bool, x11: bool = False, username: str | None = None) -> dict[str, str]:
        session_user = "root" if root else (username or self.config.username)
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root" if root else f"/home/{session_user}",
            "USER": session_user,
            "SHELL": self._resolved_shell(),
            "TERM": "xterm-256color",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if x11:
            env.update(
                {
                    "DISPLAY": ":0",
                    "PULSE_SERVER": "tcp:127.0.0.1:4713",
                }
            )
        return env

    def _termux_host_env(self) -> dict[str, str]:
        termux_bin = self.config.termux_prefix / "bin"
        return {
            "HOME": str(self.config.termux_home),
            "PREFIX": str(self.config.termux_prefix),
            "TMPDIR": str(self.config.termux_prefix / "tmp"),
            "PATH": f"{termux_bin}:/system/bin:/system/xbin:/vendor/bin",
            "LD_LIBRARY_PATH": str(self.config.termux_prefix / "lib"),
        }

    def _prepare_x11_host(self) -> None:
        host_env = self._termux_host_env()
        termux_uid, termux_gid = self.runner.host_termux_uid_gid(self.config.termux_home)
        self.runner.run(
            ["am", "start", "--user", "0", "-n", "com.termux.x11/com.termux.x11.MainActivity"],
            check=False,
            capture_output=False,
        )
        pulseaudio = self.config.termux_prefix / "bin" / "pulseaudio"
        if pulseaudio.exists():
            self.runner.run(
                [str(pulseaudio), "--start", "--exit-idle-time=-1"],
                check=False,
                env=host_env,
                capture_output=False,
                uid=termux_uid,
                gid=termux_gid,
            )
        termux_x11 = self.config.termux_prefix / "bin" / "termux-x11"
        if termux_x11.exists():
            self.runner.run(
                [str(termux_x11), ":0", "-ac"],
                check=False,
                env=host_env,
                capture_output=False,
                uid=termux_uid,
                gid=termux_gid,
                background=True,
            )

    def x11_host_commands(self) -> list[str]:
        return [
            "am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity",
            f"{self.config.termux_prefix}/bin/pulseaudio --start --exit-idle-time=-1",
            f"{self.config.termux_prefix}/bin/termux-x11 :0 -ac &",
        ]

    def mount(self) -> OperationResult:
        self.runner.require_root()
        self._ensure_dirs()
        result = OperationResult()
        mounts = self.runner.mount_table()
        if self.config.mount_data_with_dev_suid:
            self.runner.run(["busybox", "mount", "-o", "remount,dev,suid", "/data"], check=False)
        for spec in self._mount_specs():
            if self._is_mounted(spec.source, spec.target, mounts):
                result.add_skipped()
                continue
            try:
                if spec.bind:
                    self.runner.run(["busybox", "mount", "--bind", spec.source, str(spec.target)])
                    if spec.read_only:
                        self.runner.run(
                            ["busybox", "mount", "-o", "remount,bind,ro", str(spec.target)],
                        )
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

    def unmount(self) -> OperationResult:
        self.runner.require_root()
        result = OperationResult()
        mounts = self.runner.mount_table()
        for spec in reversed(self._mount_specs()):
            if not self._is_mounted(spec.source, spec.target, mounts):
                result.add_skipped()
                continue
            try:
                unmount_result = self.runner.run(
                    ["busybox", "umount", str(spec.target)],
                    check=False,
                )
                if unmount_result.returncode == 0:
                    result.add_success()
                else:
                    result.add_failure(
                        unmount_result.stderr.strip()
                        or f"command failed: busybox umount {spec.target}"
                    )
            except Exception as exc:
                result.add_failure(str(exc))
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
                bind_result = self.runner.run(
                    ["busybox", "mount", "--bind", str(source), str(target)],
                    check=False,
                )
                if bind_result.returncode == 0:
                    result.add_success()
                else:
                    result.add_failure(
                        bind_result.stderr.strip()
                        or f"command failed: busybox mount --bind {source} {target}"
                    )
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

    def status(self, verbose: bool = False) -> list[dict[str, str]]:
        rows = []
        mounts = self.runner.mount_table()
        for spec in self._mount_specs():
            row = {
                "source": spec.source,
                "target": str(spec.target),
                "type": "bind:ro" if spec.bind and spec.read_only else ("bind" if spec.bind else (spec.fstype or "")),
                "mounted": "yes" if self._is_mounted(spec.source, spec.target, mounts) else "no",
            }
            if verbose:
                row["target_exists"] = "yes" if spec.target.exists() else "no"
                row["source_exists"] = "yes" if Path(spec.source).exists() else "n/a"
            rows.append(row)
        return rows

    def doctor(self) -> list[dict[str, str]]:
        shell = self._resolved_shell()
        rows = [
            {"check": "busybox", "status": "ok" if shutil.which("busybox") else "missing", "detail": shutil.which("busybox") or ""},
            {"check": "chroot", "status": "ok" if shutil.which("chroot") else "missing", "detail": shutil.which("chroot") or ""},
            {"check": "shell", "status": "ok" if (self.config.chroot_base / shell.lstrip("/")).exists() else "missing", "detail": shell},
            {"check": "chroot_base", "status": "ok" if self.config.chroot_base.exists() else "missing", "detail": str(self.config.chroot_base)},
            {"check": "root", "status": "ok" if self.runner.is_root() else "warning", "detail": "running as root" if self.runner.is_root() else "sudo required"},
        ]
        mounted = sum(1 for row in self.status() if row["mounted"] == "yes")
        rows.append({"check": "mounts", "status": "ok" if mounted else "warning", "detail": f"{mounted}/{len(self._mount_specs())} mounted"})
        return rows

    def exec_invocation(
        self,
        *,
        root: bool,
        argv: list[str] | None = None,
        command: str | None = None,
        x11: bool = False,
        username: str | None = None,
    ) -> tuple[list[str], dict[str, str]]:
        if not command and not argv:
            raise ValueError("no command specified")
        exec_user = "root" if root else (username or self.config.username)
        shell = self._resolved_shell()
        command_text = command or shlex.join(argv or [])
        if root:
            shell_flags = "-ilc" if x11 else "-lc"
            chroot_argv = ["chroot", str(self.config.chroot_base), shell, shell_flags, command_text]
        else:
            if x11:
                quoted = shlex.quote(command_text)
                launch = f"export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713; exec {shell} -ilc {quoted}"
                chroot_argv = ["chroot", str(self.config.chroot_base), "/bin/su", "-", exec_user, "-c", launch]
            else:
                chroot_argv = ["chroot", str(self.config.chroot_base), "/bin/su", "-", exec_user, "-c", command_text]
        return chroot_argv, self._session_env(root=root, x11=x11, username=exec_user if not root else None)

    def service_invocation(
        self,
        *,
        root: bool,
        command: str,
        x11: bool = False,
        username: str | None = None,
    ) -> tuple[list[str], dict[str, str]]:
        """Return argv/env for long-running services.

        Services intentionally use a fuller login-session command path than a
        plain non-interactive exec.  In practice this matches the interactive
        `chrootctl start --login` context more closely: the target user's login
        shell is entered first, then an interactive login shell executes the
        generated service script.  This preserves user shell startup behaviour
        that tools such as VS Code Server often depend on for PATH, HOME, and
        permission-sensitive helper setup.
        """
        if not command:
            raise ValueError("no service command specified")
        exec_user = "root" if root else (username or self.config.username)
        shell = self._resolved_shell()
        env = self._session_env(root=root, x11=x11, username=exec_user if not root else None)
        quoted_command = shlex.quote(command)
        if root:
            shell_flags = "-ilc"
            chroot_argv = ["chroot", str(self.config.chroot_base), shell, shell_flags, command]
        else:
            exports = ""
            if x11:
                exports = "export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713; "
            launch = f"{exports}exec {shell} -ilc {quoted_command}"
            chroot_argv = ["chroot", str(self.config.chroot_base), "/bin/su", "-", exec_user, "-c", launch]
        return chroot_argv, env

    def exec(
        self,
        *,
        root: bool,
        argv: list[str] | None = None,
        command: str | None = None,
        x11: bool = False,
        username: str | None = None,
    ) -> int:
        self.runner.require_root()
        self.mount()
        self.fix_tty()
        if x11:
            self._prepare_x11_host()
        chroot_argv, env = self.exec_invocation(root=root, argv=argv, command=command, x11=x11, username=username)
        result = self.runner.run(
            chroot_argv,
            check=False,
            env=env,
            chroot_env=True,
            capture_output=False,
        )
        return result.returncode


    def _start_argv(
        self,
        *,
        login: bool,
        root_login: bool,
        x11: bool = False,
    ) -> tuple[list[str], dict[str, str]]:
        use_root_login = root_login or not login
        exec_user = "root" if use_root_login else self.config.username
        shell = self._resolved_shell()
        if use_root_login:
            shell_flags = "-il" if x11 else "-l"
            argv = ["chroot", str(self.config.chroot_base), shell, shell_flags]
        else:
            if x11:
                launch = f"export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713; exec {shell} -il"
                argv = ["chroot", str(self.config.chroot_base), "/bin/su", "-", exec_user, "-c", launch]
            else:
                argv = ["chroot", str(self.config.chroot_base), "/bin/su", "-", exec_user]
        return argv, self._session_env(root=use_root_login, x11=x11)

    def start_interactive(
        self,
        *,
        login: bool,
        root_login: bool,
        x11: bool = False,
    ) -> "NoReturn":
        self.runner.require_root()
        self.mount()
        self.fix_tty()
        if x11:
            self._prepare_x11_host()
        argv, env = self._start_argv(login=login, root_login=root_login, x11=x11)
        self.runner.exec(argv, env=env, chroot_env=True)

    def restart(
        self,
        *,
        login: bool,
        root_login: bool,
        x11: bool = False,
    ) -> int:
        self.unmount()
        return self.start(
            login=login,
            root_login=root_login,
            x11=x11,
        )

    def start(
        self,
        *,
        login: bool,
        root_login: bool,
        x11: bool = False,
    ) -> int:
        self.runner.require_root()
        self.mount()
        self.fix_tty()
        if x11:
            self._prepare_x11_host()
        argv, env = self._start_argv(login=login, root_login=root_login, x11=x11)
        result = self.runner.run(
            argv,
            check=False,
            env=env,
            chroot_env=True,
            capture_output=False,
        )
        return result.returncode

