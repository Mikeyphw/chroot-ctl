from __future__ import annotations

from .arch import ArchInstaller
from .config import ChrootConfig
from .controller import ChrootController
from .registry import ChrootRegistry
from .system import SystemRunner
from .ubuntu import UbuntuInstaller
from .user_sync import UserSyncManager

def build_installer(
    distro: str,
    *,
    config: ChrootConfig,
    runner: SystemRunner,
    controller: ChrootController,
    registry: ChrootRegistry,
    user_sync: UserSyncManager,
    logger,
):
    if distro == "ubuntu":
        return UbuntuInstaller(config, runner, controller, registry, user_sync, logger)
    if distro == "arch":
        return ArchInstaller(config, runner, controller, registry, user_sync, logger)
    raise ValueError(f"unsupported distro: {distro}")
