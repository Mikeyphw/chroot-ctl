from __future__ import annotations

import shlex
from typing import Any

from .config import ChrootConfig
from .models import UserIdStatus, UserIdSyncResult
from .system import SystemRunner
from .validation import validate_username


class UserSyncManager:
    def __init__(self, config: ChrootConfig, runner: SystemRunner, logger, registry: Any | None = None) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger
        self.registry = registry

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

    def _require_installed(self, *, allow_pending_finalize: bool = False) -> None:
        if allow_pending_finalize and self.runner.dry_run:
            return
        if self.registry is not None:
            record = self.registry.get(self.config.distro_name)
            if record is not None and bool(record.get("installed")):
                return
            if allow_pending_finalize:
                if self.runner.dry_run:
                    return
                phase = str((record or {}).get("phase") or "")
                if phase == "desktop" and (self.config.chroot_base / "etc" / "passwd").is_file():
                    return
            raise RuntimeError("chroot must be installed before UID/GID synchronization")
        elif not (self.config.chroot_base / "etc" / "passwd").is_file():
            raise RuntimeError("chroot must be installed before UID/GID synchronization")

    @staticmethod
    def _identity_rows(path) -> list[tuple[str, int]]:
        rows: list[tuple[str, int]] = []
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except FileNotFoundError:
            return rows
        for line in lines:
            parts = line.split(":")
            if len(parts) < 4:
                continue
            try:
                rows.append((parts[0], int(parts[2])))
            except ValueError:
                continue
        return rows

    def _preflight_collisions(self, user: str, uid: int, gid: int) -> None:
        passwd = self.config.chroot_base / "etc" / "passwd"
        group = self.config.chroot_base / "etc" / "group"
        uid_owner = next((name for name, value in self._identity_rows(passwd) if value == uid and name != user), None)
        if uid_owner:
            raise RuntimeError(f"cannot sync UID {uid}: already owned by chroot user {uid_owner}")
        gid_owner = next((name for name, value in self._identity_rows(group) if value == gid and name != user), None)
        if gid_owner:
            raise RuntimeError(f"cannot sync GID {gid}: already owned by chroot group {gid_owner}")

    def show_id(self, username: str | None = None) -> UserIdStatus:
        user = self._validate_username(username or self.config.username)
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
        return UserIdStatus(username=user, host_uid=host_uid, host_gid=host_gid, chroot_uid=current_uid, chroot_gid=current_gid, passwd_exists=passwd_path.exists(), group_exists=group_path.exists())

    def sync_id(
        self,
        username: str | None = None,
        fix_ownership: bool = True,
        *,
        allow_pending_finalize: bool = False,
    ) -> UserIdSyncResult:
        self.runner.require_root()
        self._require_installed(allow_pending_finalize=allow_pending_finalize)
        user = self._validate_username(username or self.config.username)
        host_uid, host_gid = self.host_uid_gid()
        self._preflight_collisions(user, host_uid, host_gid)
        quoted_user = shlex.quote(user)

        self._chroot_sh(f"getent group {quoted_user} >/dev/null || groupadd {quoted_user}")
        self._chroot_sh(f"id -u {quoted_user} >/dev/null 2>&1 || useradd -m -s /bin/bash -g {quoted_user} {quoted_user}")
        self._chroot_sh(f"groupmod -g {host_gid} {quoted_user}")
        self._chroot_sh(f"usermod -u {host_uid} -g {host_gid} {quoted_user}")

        if fix_ownership:
            home = f"/home/{user}"
            quoted_home = shlex.quote(home)
            self._chroot_sh(f"[ -d {quoted_home} ] && chown -R {host_uid}:{host_gid} {quoted_home} || true")
            self._restore_shared_directory_modes()

        return UserIdSyncResult(username=user, uid=host_uid, gid=host_gid, ownership_fixed=fix_ownership)

    def _restore_shared_directory_modes(self) -> None:
        # Older implementations recursively changed these system-owned trees.
        # Repair only the directory inode ownership/mode; never recursively chown
        # their contents to the synchronized user.
        self._chroot_sh(
            'for d in /tmp /var/tmp; do [ ! -d "$d" ] || { chown 0:0 "$d" && chmod 1777 "$d"; }; done; '
            '[ ! -d /var/cache ] || { chown 0:0 /var/cache && chmod 0755 /var/cache; }'
        )
