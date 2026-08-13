from __future__ import annotations

import shlex

from .config import ChrootConfig
from .models import UserIdStatus, UserIdSyncResult
from .system import SystemRunner
from .validation import validate_username

class UserSyncManager:
    def __init__(self, config: ChrootConfig, runner: SystemRunner, logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger

    def host_uid_gid(self) -> tuple[int, int]:
        return self.runner.host_termux_uid_gid(self.config.termux_home)

    def _validate_username(self, username: str) -> str:
        return validate_username(username)

    def _chroot_sh(self, command: str) -> None:
        self.runner.run(
            ["busybox", "chroot", str(self.config.chroot_base), "/bin/bash", "-lc", command],
            chroot_env=True,
            capture_output=False,
        )

    def show_id(self, username: str | None = None) -> UserIdStatus:
        user = username or self.config.username
        host_uid, host_gid = self.host_uid_gid()
        passwd_path = self.config.chroot_base / "etc" / "passwd"
        group_path = self.config.chroot_base / "etc" / "group"
        current_uid = ""
        current_gid = ""
        if passwd_path.exists():
            for line in passwd_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = line.split(":")
                if len(parts) >= 4 and parts[0] == user:
                    current_uid, current_gid = parts[2], parts[3]
                    break
        return UserIdStatus(
            username=user,
            host_uid=host_uid,
            host_gid=host_gid,
            chroot_uid=current_uid,
            chroot_gid=current_gid,
            passwd_exists=passwd_path.exists(),
            group_exists=group_path.exists(),
        )

    def sync_id(self, username: str | None = None, fix_ownership: bool = True) -> UserIdSyncResult:
        self.runner.require_root()
        user = self._validate_username(username or self.config.username)
        host_uid, host_gid = self.host_uid_gid()
        quoted_user = shlex.quote(user)

        self._chroot_sh(f"getent group {quoted_user} >/dev/null || groupadd {quoted_user}")
        self._chroot_sh(
            f"id -u {quoted_user} >/dev/null 2>&1 || useradd -m -s /bin/bash {quoted_user}"
        )
        self._chroot_sh(f"groupmod -g {host_gid} {quoted_user}")
        self._chroot_sh(f"usermod -u {host_uid} -g {host_gid} {quoted_user}")

        if fix_ownership:
            paths = [
                f"/home/{user}",
                "/tmp",
                "/var/tmp",
                "/var/cache",
            ]
            for path in paths:
                quoted_path = shlex.quote(path)
                self._chroot_sh(
                    f"[ -e {quoted_path} ] && chown -R {host_uid}:{host_gid} {quoted_path} || true"
                )

        return UserIdSyncResult(
            username=user,
            uid=host_uid,
            gid=host_gid,
            ownership_fixed=fix_ownership,
        )
