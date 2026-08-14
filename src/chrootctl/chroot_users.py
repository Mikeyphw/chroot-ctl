from __future__ import annotations

import os
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import ChrootConfig
from .models import (
    ChrootUserCreateResult,
    ChrootUserDetails,
    ChrootUserPasswordResult,
    ChrootUserRemoveResult,
    ChrootUserShellResult,
    ChrootUserSudoResult,
)
from .registry import ChrootRegistry
from .system import SystemRunner
from .user_sync import validate_username


@dataclass(frozen=True, slots=True)
class ChrootUser:
    username: str
    uid: str
    gid: str
    home: str
    shell: str

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "uid": self.uid,
            "gid": self.gid,
            "home": self.home,
            "shell": self.shell,
        }


class ChrootUserManager:
    def __init__(
        self,
        config: ChrootConfig,
        runner: SystemRunner,
        registry: ChrootRegistry,
        logger,
    ) -> None:
        self.config = config
        self.runner = runner
        self.registry = registry
        self.logger = logger

    def list_users(self) -> list[ChrootUser]:
        passwd_path = self.config.chroot_base / "etc" / "passwd"
        if not passwd_path.exists():
            return []
        users: list[ChrootUser] = []
        for line in passwd_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 7:
                continue
            users.append(
                ChrootUser(
                    username=parts[0],
                    uid=parts[2],
                    gid=parts[3],
                    home=parts[5],
                    shell=parts[6],
                )
            )
        return users

    def user_rows(self) -> list[ChrootUser]:
        return self.list_users()

    def show_user(self, username: str) -> ChrootUserDetails:
        user = self._find_user(username)
        return ChrootUserDetails(
            username=user.username,
            uid=user.uid,
            gid=user.gid,
            home=user.home,
            shell=user.shell,
            sudo=self._has_sudo_access(user.username),
        )

    def add_user(self, username: str, *, shell: str, sudo: bool) -> ChrootUserCreateResult:
        self._require_installed()
        user = validate_username(username)
        shell_path = self._validate_shell(shell)
        existing = next((item for item in self.list_users() if item.username == user), None)
        if existing is not None:
            return ChrootUserCreateResult(username=user, shell=existing.shell, sudo=self._has_sudo_access(user), created=False)
        quoted_user = shlex.quote(user)
        quoted_shell = shlex.quote(shell_path)
        self._chroot_sh(f"getent group {quoted_user} >/dev/null || groupadd {quoted_user}")
        self._chroot_sh(f"useradd -m -s {quoted_shell} -g {quoted_user} {quoted_user}")
        if sudo:
            self.set_sudo(user, enabled=True)
        created = any(item.username == user for item in self.list_users())
        if not created and not self.runner.dry_run:
            raise RuntimeError(f"useradd completed but {user} is not present in /etc/passwd")
        return ChrootUserCreateResult(username=user, shell=shell_path, sudo=sudo, created=created or self.runner.dry_run)

    def remove_user(self, username: str, *, delete_home: bool) -> ChrootUserRemoveResult:
        self._require_installed()
        user = validate_username(username)
        if not any(item.username == user for item in self.list_users()):
            return ChrootUserRemoveResult(username=user, home_deleted=False, removed=False)
        flag = "-r " if delete_home else ""
        self._chroot_sh(f"userdel {flag}{shlex.quote(user)}")
        self._remove_sudoers(user)
        removed = not any(item.username == user for item in self.list_users())
        if not removed and not self.runner.dry_run:
            raise RuntimeError(f"userdel completed but {user} is still present in /etc/passwd")
        return ChrootUserRemoveResult(username=user, home_deleted=delete_home and removed, removed=removed or self.runner.dry_run)

    def set_password(self, username: str) -> ChrootUserPasswordResult:
        self._require_installed()
        user = validate_username(username)
        self.runner.run(
            ["busybox", "chroot", str(self.config.chroot_base), "passwd", user],
            chroot_env=True,
            capture_output=False,
        )
        return ChrootUserPasswordResult(username=user, updated=True)

    def set_password_value(self, username: str, *, password: str) -> ChrootUserPasswordResult:
        self._require_installed()
        user = validate_username(username)
        password_value = _validate_password_value(password)
        self.runner.run(
            ["busybox", "chroot", str(self.config.chroot_base), "/bin/bash", "-lc", "chpasswd"],
            chroot_env=True,
            capture_output=True,
            input_text=f"{user}:{password_value}\n",
        )
        return ChrootUserPasswordResult(username=user, updated=True)

    def set_shell(self, username: str, *, shell: str) -> ChrootUserShellResult:
        self._require_installed()
        user = validate_username(username)
        shell_path = self._validate_shell(shell)
        self._chroot_sh(f"usermod -s {shlex.quote(shell_path)} {shlex.quote(user)}")
        return ChrootUserShellResult(username=user, shell=shell_path, updated=True)

    def set_sudo(self, username: str, *, enabled: bool) -> ChrootUserSudoResult:
        self._require_installed()
        user = validate_username(username)
        if enabled:
            self._chroot_sh("getent group sudo >/dev/null || groupadd sudo")
            self._chroot_sh(f"usermod -aG sudo {shlex.quote(user)}")
            self._write_sudoers(user)
        else:
            self._chroot_sh(f"gpasswd -d {shlex.quote(user)} sudo >/dev/null 2>&1 || true")
            self._remove_sudoers(user)
        return ChrootUserSudoResult(username=user, enabled=enabled)

    def _find_user(self, username: str) -> ChrootUser:
        user = validate_username(username)
        for item in self.list_users():
            if item.username == user:
                return item
        raise RuntimeError(f"unknown chroot user: {user}")

    def _require_installed(self) -> None:
        self.runner.require_root()
        record = self.registry.get(self.config.distro_name)
        if record is None or not bool(record.get("installed")):
            raise RuntimeError("chroot must be installed first")

    def _chroot_sh(self, command: str) -> None:
        self.runner.run(
            ["busybox", "chroot", str(self.config.chroot_base), "/bin/bash", "-lc", command],
            chroot_env=True,
            capture_output=False,
        )

    def _validate_shell(self, shell: str) -> str:
        if not shell.startswith("/") or any(part in shell for part in ("..", "\n", "\r")):
            raise ValueError(f"invalid shell path: {shell!r}")
        return shell

    def _sudoers_path(self, username: str) -> Path:
        return self.config.chroot_base / "etc" / "sudoers.d" / f"90-chrootctl-{username}"

    def _write_sudoers(self, username: str) -> None:
        sudoers = self._sudoers_path(username)
        if self.runner.dry_run:
            return
        sudoers.parent.mkdir(parents=True, exist_ok=True)
        if sudoers.is_symlink():
            raise RuntimeError(f"refusing sudoers symlink: {sudoers}")
        fd, temp_name = tempfile.mkstemp(prefix=f".{sudoers.name}.", dir=sudoers.parent)
        temp_path = Path(temp_name)
        try:
            os.fchmod(fd, 0o440)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self._sudoers_rule(username) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            relative = "/etc/sudoers.d/" + temp_path.name
            result = self.runner.run(["busybox", "chroot", str(self.config.chroot_base), "visudo", "-cf", relative], check=False, chroot_env=True)
            if result.returncode != 0:
                raise RuntimeError(f"visudo rejected sudoers rule for {username}: {result.stderr.strip()}")
            os.replace(temp_path, sudoers)
            sudoers.chmod(0o440)
        finally:
            temp_path.unlink(missing_ok=True)

    def _remove_sudoers(self, username: str) -> None:
        sudoers = self._sudoers_path(username)
        if sudoers.exists() and not self.runner.dry_run:
            sudoers.unlink()

    def _sudoers_rule(self, username: str) -> str:
        return f"{username} ALL=(ALL:ALL) ALL"

    def _has_sudo_access(self, username: str) -> bool:
        sudoers = self._sudoers_path(username)
        if not sudoers.is_file() or sudoers.is_symlink():
            return False
        try:
            lines = [
                line.strip()
                for line in sudoers.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        except OSError:
            return False
        if self._sudoers_rule(username) not in lines:
            return False
        if self.runner.dry_run:
            return True
        result = self.runner.run(
            ["busybox", "chroot", str(self.config.chroot_base), "sudo", "-l", "-U", username],
            check=False, chroot_env=True,
        )
        return result.returncode == 0


def _validate_password_value(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must not be empty")
    if len(password) > 4096:
        raise ValueError("password is too long")
    if any(char in password for char in ("\x00", "\n", "\r", ":")):
        raise ValueError("password contains a value that cannot be passed safely to chpasswd")
    return password
