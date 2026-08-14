from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from ..models import ChrootDetails, ChrootRecord, ChrootRemovalResult, ChrootRenameResult, PackageDiffResult, SessionActionResult
from ..validation import validate_chroot_name
from .context import ServiceContainer
from .storage_safety import require_archive_outside_source, require_contained
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

    def _require_runnable_record(self, name: str) -> tuple[dict[str, Any], Path]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        if not bool(record.get("installed")):
            raise RuntimeError(f"chroot is not installed and cannot be started: {name}")
        config = self.services.config_for(name)
        rootfs = require_contained(
            config.chroot_root,
            Path(str(record.get("path") or config.chroot_base)),
            label="registered chroot path",
        )
        if not rootfs.is_dir():
            raise RuntimeError(f"registered chroot path is missing or not a directory: {rootfs}")
        return record, rootfs

    def start(self, name: str, *, login: bool = True, root_login: bool = False, interactive: bool = True) -> SessionActionResult:
        self._require_runnable_record(name)
        runtime = self.services.runtime_for(name)
        code = runtime.controller.start(login=login, root_login=root_login) if interactive else runtime.controller.prepare()
        return SessionActionResult(
            action="start",
            target=name,
            exit_code=code,
            next_steps=(f"chrootctl --name {name} logs --all",),
        )

    def restart(self, name: str, *, login: bool = True, root_login: bool = False, interactive: bool = True) -> SessionActionResult:
        self._require_runnable_record(name)
        runtime = self.services.runtime_for(name)
        code = runtime.controller.restart(login=login, root_login=root_login) if interactive else runtime.controller.restart_prepare()
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
        runtime = self.services.runtime_for(old_name)
        return rename_chroot(self.services.base_config, self.services.registry, runtime.runner, self.services.logger, old_name, new_name)

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
        runtime = self.services.runtime_for(None)
        return inspect_chroot_archive(archive, registry=self.services.registry, password=password, runner=runtime.runner)

    def validate_imported(self, name: str) -> dict[str, Any]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        target = self._registered_rootfs(name)
        return validate_imported_chroot(target, arch=str(record.get("arch", "")))

    def _registered_rootfs(self, name: str) -> Path:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        config = self.services.config_for(name)
        return require_contained(config.chroot_root, Path(str(record.get("path") or config.chroot_base)), label="registered chroot path")

    def package_diff(self, left: str, right: str) -> PackageDiffResult:
        left_pkgs = _package_inventory(self._registered_rootfs(left))
        right_pkgs = _package_inventory(self._registered_rootfs(right))
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
        rootfs = require_contained(config.chroot_root, Path(str(record.get("path") or config.chroot_base)), label="registered chroot path")
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
        config = self.services.config_for(name)
        source_path = require_contained(config.chroot_root, Path(str(record.get("path") or config.chroot_base)), label="registered chroot path")
        size_bytes = _directory_size(source_path)
        target_archive = (archive or Path(f"./{name}.tar.zst")).expanduser().resolve(strict=False)
        blocking: list[dict[str, str]] = []
        runtime = self.services.runtime_for(name)
        mounted = [row for row in runtime.controller.status(verbose=True) if str(row.get("mounted", "")).lower() == "yes"]
        if mounted:
            blocking.append({"code": "chroot_mounted", "message": "Export requires the chroot to be fully unmounted."})
        try:
            require_archive_outside_source(source_path, target_archive)
        except RuntimeError as exc:
            blocking.append({"code": "archive_inside_source", "message": str(exc)})
        probe = target_archive.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        free_bytes = shutil.disk_usage(probe).free
        enough_space = free_bytes >= size_bytes
        if not enough_space:
            blocking.append({"code": "insufficient_space", "message": "The export destination does not have enough free space."})
        return {
            "ok": not blocking,
            "kind": "export",
            "name": name,
            "archive": str(target_archive),
            "size_bytes": size_bytes,
            "required_bytes": size_bytes,
            "free_bytes": int(free_bytes),
            "enough_space": enough_space,
            "blocking": blocking,
            "warnings": [],
        }

    def import_preview(self, archive: Path, *, name: str | None = None, conflict: str = "rename", password: str | None = None) -> dict[str, Any]:
        if conflict not in {"rename", "overwrite"}:
            raise RuntimeError(f"unsupported conflict strategy: {conflict}")
        inspection = self.inspect_archive(archive, password=password)
        selected_name = validate_chroot_name((name or inspection.suggested_name or inspection.source_name).strip())
        config = self.services.config_for(selected_name)
        free_bytes = shutil.disk_usage(config.chroot_root).free
        extracted_bytes = max(int(inspection.extracted_size_bytes or inspection.size_bytes), 1)
        required = extracted_bytes * 2 + 64 * 1024 * 1024
        target_exists = self.services.registry.get(selected_name) is not None or config.chroot_base.exists()
        final_name = selected_name
        if target_exists and conflict == "rename":
            final_name = _next_available_name(selected_name, self.services.registry, self.services.base_config)
        enough_space = free_bytes >= required
        blocking = [] if enough_space else [{"code": "insufficient_space", "message": "The chroot storage root does not have enough free space for staged extraction."}]
        return {
            "ok": not blocking,
            "kind": "import",
            "archive": str(archive),
            "requested_name": selected_name,
            "final_name": final_name,
            "conflict": conflict,
            "target_exists": target_exists,
            "size_bytes": inspection.size_bytes,
            "extracted_size_bytes": inspection.extracted_size_bytes,
            "required_bytes": required,
            "free_bytes": int(free_bytes),
            "enough_space": enough_space,
            "checksum_verified": inspection.checksum_verified,
            "blocking": blocking,
            "warnings": ["Overwrite keeps the current chroot as a rollback backup until the staged generation is committed."] if target_exists and conflict == "overwrite" else [],
        }

    def delete_preview(self, name: str) -> dict[str, Any]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        target = self._registered_rootfs(name)
        size_bytes = _directory_size(target)
        return {
            "ok": True,
            "kind": "delete",
            "name": name,
            "path": str(target),
            "reclaim_bytes": size_bytes,
        }
