from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..models import ChrootDetails, ChrootExportResult, ChrootImportResult, ChrootRecord, ChrootRemovalResult, ChrootRenameResult, SessionActionResult
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

    def export(self, name: str, *, archive: Path | None = None) -> ChrootExportResult:
        runtime = self.services.runtime_for(name)
        return export_chroot(runtime.config, self.services.registry, runtime.runner, self.services.logger, name, archive=archive)

    def import_archive(self, archive: Path, *, name: str | None = None) -> ChrootImportResult:
        runtime = self.services.runtime_for(name)
        return import_chroot(runtime.config, self.services.registry, runtime.runner, self.services.logger, archive=archive, name=name)


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

def _tar_with_zstd_args(*, create: bool, archive: Path, cwd: Path, members: list[str]) -> list[str]:
    base = ["tar", "--zstd", "-cpf" if create else "-xpf", str(archive)]
    if not create:
        base = ["tar", "--zstd", "-xpf", str(archive)]
    return [*base, *members]


def _read_export_manifest(archive: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="chrootctl-import-manifest-") as tmp:
        tmpdir = Path(tmp)
        result = subprocess.run(
            ["tar", "--zstd", "-xpf", str(archive), "-C", str(tmpdir), ".chrootctl-export.json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to read export manifest from {archive}")
        manifest_path = tmpdir / ".chrootctl-export.json"
        if not manifest_path.exists():
            raise RuntimeError(f"archive is missing .chrootctl-export.json: {archive}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))


def export_chroot(config, registry: ChrootRegistry, runner, logger: Any, name: str, *, archive: Path | None = None) -> ChrootExportResult:
    record = registry.get(name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {name}")
    target_config = config.for_chroot(name)
    chroot_path = Path(str(record["path"])).resolve(strict=False)
    if not chroot_path.exists():
        raise RuntimeError(f"chroot path does not exist: {chroot_path}")
    archive_path = (archive or Path.cwd() / f"{name}.tar.zst").expanduser().resolve()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "distro": str(record.get("distro", "")),
        "arch": str(record.get("arch") or getattr(target_config, "target_arch", "arm64")),
        "release_name": str(record.get("release_name", "")),
        "version": str(record.get("version", "")),
        "phase": str(record.get("phase", "")),
        "installed": bool(record.get("installed")),
        "metadata": record.get("metadata", {}),
        "path_name": chroot_path.name,
    }
    with tempfile.TemporaryDirectory(prefix="chrootctl-export-") as tmp:
        tmpdir = Path(tmp)
        manifest_path = tmpdir / ".chrootctl-export.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        result = subprocess.run(
            [
                "tar",
                "--zstd",
                "-cpf",
                str(archive_path),
                "-C",
                str(chroot_path.parent),
                chroot_path.name,
                "-C",
                str(tmpdir),
                manifest_path.name,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to export {name} to {archive_path}")
    logger.info("exported chroot %s to %s", name, archive_path)
    return ChrootExportResult(name=name, archive=archive_path, arch=str(manifest["arch"]))


def import_chroot(config, registry: ChrootRegistry, runner, logger: Any, *, archive: Path, name: str | None = None) -> ChrootImportResult:
    archive_path = archive.expanduser().resolve()
    if not archive_path.exists():
        raise RuntimeError(f"archive does not exist: {archive_path}")
    manifest = _read_export_manifest(archive_path)
    source_name = validate_chroot_name(str(manifest.get("name") or manifest.get("path_name") or archive_path.stem.replace(".tar", "")))
    target_name = validate_chroot_name(name or source_name)
    target_config = config.for_chroot(target_name)
    if registry.get(target_name) is not None:
        raise RuntimeError(f"destination chroot already exists: {target_name}")
    if target_config.chroot_base.exists():
        raise RuntimeError(f"destination path already exists: {target_config.chroot_base}")
    target_config.chroot_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chrootctl-import-") as tmp:
        tmpdir = Path(tmp)
        result = subprocess.run(
            ["tar", "--zstd", "-xpf", str(archive_path), "-C", str(tmpdir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to extract {archive_path}")
        extracted_path = tmpdir / str(manifest.get("path_name") or source_name)
        if not extracted_path.exists():
            raise RuntimeError(f"archive is missing extracted chroot directory: {extracted_path.name}")
        shutil.move(str(extracted_path), str(target_config.chroot_base))
    registry.upsert(
        name=target_name,
        distro=str(manifest.get("distro", "")),
        path=str(target_config.chroot_base),
        arch=str(manifest.get("arch", getattr(target_config, "target_arch", "arm64"))),
        release_name=str(manifest.get("release_name", "")),
        version=str(manifest.get("version", "")),
        phase=str(manifest.get("phase", "extract") or "extract"),
        installed=bool(manifest.get("installed")),
        metadata=dict(manifest.get("metadata", {})),
    )
    logger.info("imported chroot %s from %s", target_name, archive_path)
    return ChrootImportResult(
        name=target_name,
        archive=archive_path,
        arch=str(manifest.get("arch", getattr(target_config, "target_arch", "arm64"))),
        path=target_config.chroot_base,
    )
