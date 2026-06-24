from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..chroot_users import ChrootUserManager
from ..config import ChrootConfig
from ..controller import ChrootController
from ..logging_utils import configure_logging
from ..registry import ChrootRegistry
from ..system import SystemRunner
from ..user_sync import UserSyncManager


@dataclass(slots=True)
class ServiceRuntime:
    config: ChrootConfig
    runner: SystemRunner
    controller: ChrootController
    user_sync: UserSyncManager
    chroot_users: ChrootUserManager


@dataclass(slots=True)
class ServiceContainer:
    base_config: ChrootConfig
    registry: ChrootRegistry
    logger: Any
    dry_run: bool = False

    def config_for(self, name: str | None = None, *, username: str | None = None) -> ChrootConfig:
        config = self.base_config.for_chroot(name) if name else self.base_config
        if username is not None:
            config = config.with_overrides(username=username)
        return config

    def runtime_for(self, name: str | None = None, *, username: str | None = None) -> ServiceRuntime:
        config = self.config_for(name, username=username)
        runner = SystemRunner(logger=self.logger, dry_run=self.dry_run)
        return ServiceRuntime(
            config=config,
            runner=runner,
            controller=ChrootController(config, runner, self.logger),
            user_sync=UserSyncManager(config, runner, self.logger),
            chroot_users=ChrootUserManager(config, runner, self.registry, self.logger),
        )

    def system(self) -> "SystemService":
        from .system import SystemService

        return SystemService(self)

    def chroots(self) -> "ChrootService":
        from .chroots import ChrootService

        return ChrootService(self)

    def users(self, *, name: str | None = None) -> "UserService":
        from .users import UserService

        return UserService(self, chroot_name=name)

    def audit(self) -> "AuditService":
        from .audit import AuditService

        return AuditService(self)

    def support(self) -> "SupportService":
        from .support import SupportService

        return SupportService(self)

    def lifecycle(self) -> "LifecycleService":
        from .lifecycle import LifecycleService

        return LifecycleService()

    def catalog(self, kind: str, *, name: str | None = None) -> "CatalogService":
        from .catalog import CatalogService

        return CatalogService(self, kind=kind, chroot_name=name)

    def install(self) -> "InstallService":
        from .install import InstallService

        return InstallService(self)


def create_service_container(config_path=None, *, dry_run: bool = False, verbose: bool = False) -> ServiceContainer:
    base_config = ChrootConfig.load(config_path)
    registry = ChrootRegistry(base_config.database_path)
    logger = configure_logging(base_config.log_file, verbose=verbose)
    return ServiceContainer(base_config=base_config, registry=registry, logger=logger, dry_run=dry_run)
