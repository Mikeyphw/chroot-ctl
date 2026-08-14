from __future__ import annotations

import os
import shutil
import tarfile
import uuid
from pathlib import Path

from ..models import SnapshotActionResult
from .context import ServiceContainer
from .storage_safety import best_effort_mutation_state, require_archive_outside_source, require_contained, require_unmounted, safe_basename


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


class SnapshotService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def snapshot_root(self) -> Path:
        return self.services.base_config.chroot_root / ".snapshots"

    def base_dir(self, chroot_name: str) -> Path:
        safe_name = self.services.config_for(chroot_name).distro_name
        return require_contained(self.snapshot_root(), self.snapshot_root() / safe_name, label="snapshot chroot directory")

    def _snapshot_source(self, path: Path) -> Path:
        # Snapshot records remain authoritative across chroot renames; an older
        # snapshot directory name is valid as long as it stays in the managed root.
        return require_contained(self.snapshot_root(), path, label="snapshot source path")

    def list(self, *, chroot_name: str | None = None, limit: int = 100):
        return self.services.registry.list_snapshots(chroot_name=chroot_name, limit=limit)

    def _source_path(self, chroot_name: str) -> Path:
        record = self.services.registry.get(chroot_name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {chroot_name}")
        config = self.services.config_for(chroot_name)
        return require_contained(config.chroot_root, Path(str(record.get("path") or config.chroot_base)), label="registered chroot path")

    def _require_unmounted(self, chroot_name: str) -> None:
        runtime = self.services.runtime_for(chroot_name)
        require_unmounted(runtime.controller, name=chroot_name)

    def create(self, chroot_name: str, *, name: str | None = None, note: str = ""):
        source = self._source_path(chroot_name)
        if not source.exists():
            raise RuntimeError(f"missing chroot path: {source}")
        self._require_unmounted(chroot_name)
        snapshot_name = safe_basename((name or "snapshot").strip() or "snapshot", label="snapshot name")
        base = self.base_dir(chroot_name)
        target = require_contained(base, base / snapshot_name, label="snapshot path")
        if target.exists():
            raise RuntimeError(f"snapshot already exists: {snapshot_name}")
        base.mkdir(parents=True, exist_ok=True)
        stage = base / f".partial-{snapshot_name}-{uuid.uuid4().hex}"
        mutation_id = self.services.registry.begin_fs_mutation(
            kind="snapshot.create", target=chroot_name, source_path=str(source), destination_path=str(target), detail={"snapshot": snapshot_name}
        )
        try:
            shutil.copytree(source, stage, symlinks=True)
            self.services.registry.update_fs_mutation(mutation_id, "staged", detail={"stage": str(stage)})
            os.replace(stage, target)
            size_bytes = _directory_size(target)
            try:
                snapshot = self.services.registry.add_snapshot(
                    name=snapshot_name,
                    chroot_name=chroot_name,
                    path=str(target),
                    kind="copy",
                    note=note,
                    size_bytes=size_bytes,
                    metadata={"source_path": str(source), "_chrootctl_mutation_id": mutation_id},
                )
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
        except Exception as exc:
            shutil.rmtree(stage, ignore_errors=True)
            best_effort_mutation_state(self.services.registry, mutation_id, "rolled_back", self.services.logger, detail={"error": str(exc)})
            raise
        # Snapshot row + promoted tree are authoritative; journal finalization must not undo them.
        best_effort_mutation_state(self.services.registry, mutation_id, "complete", self.services.logger)
        self.services.audit().record("snapshot.create", target=chroot_name, message=f"Created snapshot {snapshot_name}", metadata={"snapshot": snapshot_name})
        return SnapshotActionResult(
            chroot_name=chroot_name,
            snapshot_name=snapshot_name,
            path=str(target),
            action="create",
            created_at=snapshot.created_at,
            next_steps=(f"Review snapshot files: {target}", f"Restore snapshot: /chroots/{chroot_name}/snapshots/{snapshot_name}/restore"),
        )

    def restore(self, chroot_name: str, snapshot_name: str):
        safe_snapshot = safe_basename(snapshot_name, label="snapshot name")
        snapshot = self.services.registry.get_snapshot_by_name(chroot_name, safe_snapshot)
        config = self.services.config_for(chroot_name)
        record = self.services.registry.get(chroot_name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {chroot_name}")
        target = require_contained(config.chroot_root, Path(str(record.get("path") or config.chroot_base)), label="registered chroot path")
        source = self._snapshot_source(Path(snapshot.path))
        if not source.exists():
            raise RuntimeError(f"missing snapshot path: {source}")
        self._require_unmounted(chroot_name)
        stage = config.chroot_root / f".chrootctl-restore-stage-{chroot_name}-{uuid.uuid4().hex}"
        backup = config.chroot_root / f".chrootctl-restore-backup-{chroot_name}-{uuid.uuid4().hex}"
        mutation_id = self.services.registry.begin_fs_mutation(
            kind="snapshot.restore", target=chroot_name, source_path=str(source), destination_path=str(target), detail={"snapshot": safe_snapshot}
        )
        promoted = False
        backed_up = False
        try:
            shutil.copytree(source, stage, symlinks=True)
            self.services.registry.update_fs_mutation(mutation_id, "staged", detail={"stage": str(stage)})
            if target.exists():
                os.replace(target, backup)
                backed_up = True
            self.services.registry.update_fs_mutation(mutation_id, "promoting", detail={"backup": str(backup) if backed_up else ""})
            os.replace(stage, target)
            promoted = True
            best_effort_mutation_state(
                self.services.registry,
                mutation_id,
                "committed",
                self.services.logger,
                detail={"backup": str(backup) if backed_up else "", "stage": str(stage)},
            )
            # Keep the authoritative registry path unchanged; only the filesystem generation changes.
        except Exception as exc:
            if promoted and target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if backed_up and backup.exists() and not target.exists():
                os.replace(backup, target)
            shutil.rmtree(stage, ignore_errors=True)
            best_effort_mutation_state(self.services.registry, mutation_id, "rolled_back", self.services.logger, detail={"error": str(exc)})
            raise
        # Promotion is the authoritative restore commit. Cleanup of the previous
        # generation is best-effort so a cleanup error cannot destroy the new tree.
        backup_cleanup_error = ""
        if backed_up and backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError as cleanup_exc:
                backup_cleanup_error = str(cleanup_exc)
        best_effort_mutation_state(
            self.services.registry,
            mutation_id,
            "complete",
            self.services.logger,
            detail={"backup_cleanup_error": backup_cleanup_error} if backup_cleanup_error else {},
        )
        self.services.audit().record("snapshot.restore", target=chroot_name, message=f"Restored snapshot {safe_snapshot}", metadata={"snapshot": safe_snapshot})
        return SnapshotActionResult(
            chroot_name=chroot_name,
            snapshot_name=safe_snapshot,
            path=str(target),
            action="restore",
            created_at=snapshot.created_at,
            next_steps=(f"Start chroot: chrootctl --name {chroot_name} start --login", f"Review logs: chrootctl --name {chroot_name} logs --all"),
        )

    def export(self, chroot_name: str, snapshot_name: str, *, archive: Path | None = None):
        safe_snapshot = safe_basename(snapshot_name, label="snapshot name")
        snapshot = self.services.registry.get_snapshot_by_name(chroot_name, safe_snapshot)
        source = self._snapshot_source(Path(snapshot.path))
        if not source.exists():
            raise RuntimeError(f"missing snapshot path: {source}")
        target_archive = require_archive_outside_source(source, (archive or (source.parent / f"{safe_snapshot}.tar.gz")).expanduser())
        target_archive.parent.mkdir(parents=True, exist_ok=True)
        temp_archive = target_archive.with_name(f".{target_archive.name}.partial-{uuid.uuid4().hex}")
        try:
            with tarfile.open(temp_archive, "w:gz") as handle:
                handle.add(source, arcname=source.name, recursive=True)
            os.replace(temp_archive, target_archive)
        finally:
            temp_archive.unlink(missing_ok=True)
        self.services.audit().record("snapshot.export", target=chroot_name, message=f"Exported snapshot {safe_snapshot}", metadata={"snapshot": safe_snapshot, "archive": str(target_archive)})
        return SnapshotActionResult(
            chroot_name=chroot_name,
            snapshot_name=safe_snapshot,
            path=str(source),
            action="export",
            created_at=snapshot.created_at,
            exported_archive=str(target_archive),
            next_steps=(f"Archive ready: {target_archive}",),
        )
