from __future__ import annotations

from ..models import (
    ChrootUserCreateResult,
    ChrootUserDetails,
    ChrootUserPasswordResult,
    ChrootUserRemoveResult,
    ChrootUserShellResult,
    ChrootUserSudoResult,
    UserIdStatus,
    UserIdSyncResult,
)
from .context import ServiceContainer


class UserService:
    def __init__(self, services: ServiceContainer, *, chroot_name: str | None = None) -> None:
        self.services = services
        self.chroot_name = chroot_name

    def list(self):
        runtime = self.services.runtime_for(self.chroot_name)
        return runtime.chroot_users.list_users()

    def show(self, username: str) -> ChrootUserDetails:
        runtime = self.services.runtime_for(self.chroot_name)
        return runtime.chroot_users.show_user(username)

    def add(self, username: str, *, shell: str, sudo: bool) -> ChrootUserCreateResult:
        runtime = self.services.runtime_for(self.chroot_name)
        return runtime.chroot_users.add_user(username, shell=shell, sudo=sudo)

    def remove(self, username: str, *, delete_home: bool) -> ChrootUserRemoveResult:
        runtime = self.services.runtime_for(self.chroot_name)
        return runtime.chroot_users.remove_user(username, delete_home=delete_home)

    def set_password(self, username: str, *, password: str | None = None) -> ChrootUserPasswordResult:
        runtime = self.services.runtime_for(self.chroot_name)
        if password is None:
            return runtime.chroot_users.set_password(username)
        return runtime.chroot_users.set_password_value(username, password=password)

    def set_shell(self, username: str, *, shell: str) -> ChrootUserShellResult:
        runtime = self.services.runtime_for(self.chroot_name)
        return runtime.chroot_users.set_shell(username, shell=shell)

    def set_sudo(self, username: str, *, enabled: bool) -> ChrootUserSudoResult:
        runtime = self.services.runtime_for(self.chroot_name)
        return runtime.chroot_users.set_sudo(username, enabled=enabled)

    def show_id(self, username: str) -> UserIdStatus:
        runtime = self.services.runtime_for(self.chroot_name, username=username)
        return runtime.user_sync.show_id(username=username)

    def sync_id(self, username: str, *, fix_ownership: bool = True) -> UserIdSyncResult:
        runtime = self.services.runtime_for(self.chroot_name, username=username)
        return runtime.user_sync.sync_id(username=username, fix_ownership=fix_ownership)
