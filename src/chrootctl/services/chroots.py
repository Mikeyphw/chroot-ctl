from __future__ import annotations

import re
from pathlib import Path
import shutil
from typing import Any

from ..models import ChrootDetails, ChrootRecord, ChrootRemovalResult, ChrootRenameResult, PackageDiffResult, SessionActionResult
from .context import ServiceContainer
from .chroot_archives import (
    export_chroot,
    import_chroot,
    inspect_chroot_archive,
    mount_summary,
    record_from_registry,
    remove_chroot,
    rename_chroot,
    validate_imported_chroot,
    _next_available_name,
    _package_inventory,
    _directory_size,
)

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

    def export(self, name: str, *, archive: Path | None = None, password: str | None = None):
        runtime = self.services.runtime_for(name)
        result = export_chroot(runtime.config, self.services.registry, runtime.runner, self.services.logger, name, archive=archive, password=password)
        self.services.audit().record("transfer.export", target=name, message=f"Exported {result.archive.name}", metadata={"encrypted": str(bool(password))})
        return result

    def import_archive(self, archive: Path, *, name: str | None = None, conflict: str = "rename", password: str | None = None, post_import: str = "register"):
        runtime = self.services.runtime_for(name)
        result = import_chroot(
            runtime.config,
            self.services.registry,
            runtime.runner,
            self.services.logger,
            archive=archive,
            name=name,
            conflict=conflict,
            password=password,
            post_import=post_import,
        )
        self.services.audit().record(
            "transfer.import",
            target=result.name,
            message=f"Imported {result.archive.name}",
            metadata={"encrypted": str(result.encrypted), "conflict": conflict, "post_import": post_import},
        )
        return result

    def inspect_archive(self, archive: Path, *, password: str | None = None):
        return inspect_chroot_archive(archive, registry=self.services.registry, password=password)

    def validate_imported(self, name: str) -> dict[str, Any]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        target = Path(str(record.get("path", self.services.config_for(name).chroot_base)))
        return validate_imported_chroot(target, arch=str(record.get("arch", "")))

    def package_diff(self, left: str, right: str) -> PackageDiffResult:
        left_pkgs = _package_inventory(self.services.config_for(left).chroot_base)
        right_pkgs = _package_inventory(self.services.config_for(right).chroot_base)
        return PackageDiffResult(
            left=left,
            right=right,
            left_count=len(left_pkgs),
            right_count=len(right_pkgs),
            only_left=tuple(sorted(left_pkgs - right_pkgs)[:250]),
            only_right=tuple(sorted(right_pkgs - left_pkgs)[:250]),
            common_count=len(left_pkgs & right_pkgs),
        )

    def storage_status(self, name: str) -> dict[str, Any]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        config = self.services.config_for(name)
        runtime = self.services.runtime_for(name)
        rootfs = Path(str(record.get("path") or config.chroot_base)).expanduser()
        cache_path = rootfs / "var" / "cache"
        probe = rootfs if rootfs.exists() else config.chroot_root.expanduser()
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        usage = shutil.disk_usage(probe)
        mount_rows = runtime.controller.status(verbose=True)
        mounted_count = sum(1 for row in mount_rows if str(row.get("mounted", "")).lower() == "yes")
        return {
            "name": name,
            "rootfsPath": str(rootfs),
            "rootfsExists": rootfs.exists(),
            "rootfsBytes": _directory_size(rootfs),
            "cachePath": str(cache_path),
            "cacheExists": cache_path.exists(),
            "cacheBytes": _directory_size(cache_path),
            "freeBytes": int(usage.free),
            "usedBytes": int(usage.used),
            "totalBytes": int(usage.total),
            "mountState": "mounted" if mounted_count else "not-mounted",
            "mountedCount": mounted_count,
            "mountCount": len(mount_rows),
            "snapshotDirectory": str(config.snapshot_dir),
        }

    def export_preview(self, name: str, *, archive: Path | None = None) -> dict[str, Any]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        source_path = Path(str(record.get("path", self.services.config_for(name).chroot_base)))
        size_bytes = _directory_size(source_path)
        target_archive = (archive or Path(f"./{name}.tar.zst")).expanduser()
        free_bytes = shutil.disk_usage(target_archive.parent if target_archive.parent.exists() else Path.cwd()).free
        return {
            "ok": free_bytes >= size_bytes,
            "kind": "export",
            "name": name,
            "archive": str(target_archive),
            "size_bytes": size_bytes,
            "required_bytes": size_bytes,
            "free_bytes": int(free_bytes),
            "enough_space": free_bytes >= size_bytes,
        }

    def import_preview(self, archive: Path, *, name: str | None = None, conflict: str = "rename") -> dict[str, Any]:
        inspection = self.inspect_archive(archive)
        selected_name = (name or inspection.suggested_name or inspection.source_name).strip()
        config = self.services.config_for(selected_name)
        free_bytes = shutil.disk_usage(config.chroot_root).free
        required = max(int(inspection.size_bytes), 1)
        final_name = selected_name
        if inspection.target_exists and conflict == "rename":
            final_name = _next_available_name(selected_name, self.services.registry, config)
        return {
            "ok": free_bytes >= required,
            "kind": "import",
            "archive": str(archive),
            "requested_name": selected_name,
            "final_name": final_name,
            "conflict": conflict,
            "target_exists": inspection.target_exists,
            "size_bytes": inspection.size_bytes,
            "required_bytes": required,
            "free_bytes": int(free_bytes),
            "enough_space": free_bytes >= required,
            "checksum_verified": inspection.checksum_verified,
        }

    def delete_preview(self, name: str) -> dict[str, Any]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        target = Path(str(record.get("path", self.services.config_for(name).chroot_base)))
        size_bytes = _directory_size(target)
        return {
            "ok": True,
            "kind": "delete",
            "name": name,
            "path": str(target),
            "reclaim_bytes": size_bytes,
        }


def validate_chroot_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise RuntimeError("new chroot name is required")
    if not CHROOT_NAME_PATTERN.fullmatch(normalized):
        raise RuntimeError(f"invalid chroot name: {name!r}")
    return normalized
