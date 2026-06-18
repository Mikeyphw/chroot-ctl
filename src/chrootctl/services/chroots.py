from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models import ChrootDetails, ChrootRecord, ChrootRemovalResult, ChrootRenameResult, SessionActionResult
from ..registry import ChrootRegistry
from .context import ServiceContainer

CHROOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ChrootService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def list(self) -> list[ChrootRecord]:
        return [record_from_registry(row) for row in self.services.registry.list()]

    def get(self, name: str) -> ChrootDetails:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        config = self.services.config_for(name)
        metadata = record.get("metadata", {})
        normalized_metadata = {
            str(key): str(value)
            for key, value in metadata.items()
            if isinstance(metadata, dict)
        }
        return ChrootDetails(
            name=str(record.get("name", name)),
            distro=str(record.get("distro", "")),
            path=str(record.get("path", "")),
            release_name=str(record.get("release_name", "")),
            version=str(record.get("version", "")),
            phase=str(record.get("phase", "")),
            installed=bool(record.get("installed")),
            arch=str(record.get("arch", "")),
            created_at=str(record.get("created_at", "")),
            updated_at=str(record.get("updated_at", "")),
            configured_mounts=mount_summary(config),
            extra_packages=",".join(config.extra_packages) or "none",
            locale=config.locale,
            metadata=normalized_metadata,
        )

    def start(self, name: str, *, login: bool = True, root_login: bool = False) -> SessionActionResult:
        runtime = self.services.runtime_for(name)
        code = runtime.controller.start(login=login, root_login=root_login)
        return SessionActionResult(
            action="start",
            target=name,
            exit_code=code,
            next_steps=(f"chrootctl --name {name} logs --all",),
        )

    def restart(self, name: str, *, login: bool = True, root_login: bool = False) -> SessionActionResult:
        runtime = self.services.runtime_for(name)
        code = runtime.controller.restart(login=login, root_login=root_login)
        return SessionActionResult(
            action="restart",
            target=name,
            exit_code=code,
            next_steps=(f"chrootctl --name {name} logs --all",),
        )

    def remove(self, name: str) -> ChrootRemovalResult:
        runtime = self.services.runtime_for(name)
        return remove_chroot(runtime.config, self.services.registry, runtime.runner, self.services.logger, name)

    def rename(self, old_name: str, new_name: str) -> ChrootRenameResult:
        return rename_chroot(self.services.base_config, self.services.registry, old_name, new_name)


def record_from_registry(row: dict[str, object]) -> ChrootRecord:
    return ChrootRecord(
        name=str(row.get("name", "")),
        distro=str(row.get("distro", "")),
        path=str(row.get("path", "")),
        release_name=str(row.get("release_name", "")),
        version=str(row.get("version", "")),
        phase=str(row.get("phase", "")),
        installed=bool(row.get("installed")),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


def validate_chroot_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise RuntimeError("new chroot name is required")
    if not CHROOT_NAME_PATTERN.fullmatch(normalized):
        raise RuntimeError(f"invalid chroot name: {name!r}")
    return normalized


def mount_summary(config) -> str:
    mounts: list[str] = []
    for mount in config.media_mounts + config.extra_bind_mounts:
        if mount.enabled:
            mode = "ro" if mount.read_only else "rw"
            mounts.append(f"{mount.source}->{mount.target}({mode})")
    return ", ".join(mounts) or "default"


def remove_chroot(config, registry: ChrootRegistry, runner, logger: Any, name: str) -> ChrootRemovalResult:
    record = registry.get(name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {name}")
    target_config = config.for_chroot(name)
    from ..controller import ChrootController

    controller = ChrootController(target_config, runner, logger)
    unmount_result = controller.unmount()
    target_path = Path(str(record["path"]))
    resolved_root = target_config.chroot_root.resolve()
    resolved_target = target_path.resolve(strict=False)
    if resolved_root not in resolved_target.parents and resolved_root != resolved_target:
        raise RuntimeError(f"refusing to delete path outside chroot root: {resolved_target}")
    if runner.dry_run:
        return ChrootRemovalResult(
            name=name,
            removed=False,
            unmounted_success=unmount_result.success,
            unmounted_failed=unmount_result.failed,
        )
    if target_path.exists():
        import shutil

        shutil.rmtree(target_path)
    registry.delete(name)
    return ChrootRemovalResult(
        name=name,
        removed=True,
        unmounted_success=unmount_result.success,
        unmounted_failed=unmount_result.failed,
    )


def rename_chroot(config, registry: ChrootRegistry, old_name: str, new_name: str) -> ChrootRenameResult:
    normalized_new_name = validate_chroot_name(new_name)
    record = registry.get(old_name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {old_name}")
    if registry.get(normalized_new_name) is not None:
        raise RuntimeError(f"destination chroot already exists: {normalized_new_name}")
    old_config = config.for_chroot(old_name)
    new_config = config.for_chroot(normalized_new_name)
    registry_path = Path(str(record["path"])).resolve(strict=False)
    expected_path = old_config.chroot_base.resolve(strict=False)
    if registry_path != expected_path:
        raise RuntimeError(
            f"registry path mismatch for {old_name}: expected {expected_path}, found {registry_path}"
        )
    if new_config.chroot_base.exists():
        raise RuntimeError(f"destination path already exists: {new_config.chroot_base}")
    if old_config.chroot_base.exists():
        old_config.chroot_base.rename(new_config.chroot_base)
    registry.rename(old_name, normalized_new_name, new_path=str(new_config.chroot_base))
    return ChrootRenameResult(old_name=old_name, new_name=normalized_new_name, renamed=True)
