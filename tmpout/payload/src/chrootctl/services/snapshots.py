
from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

from ..models import SnapshotActionResult
from .context import ServiceContainer


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

    def base_dir(self, chroot_name: str) -> Path:
        return self.services.base_config.chroot_root / ".snapshots" / chroot_name

    def list(self, *, chroot_name: str | None = None, limit: int = 100):
        return self.services.registry.list_snapshots(chroot_name=chroot_name, limit=limit)

    def create(self, chroot_name: str, *, name: str | None = None, note: str = ""):
        record = self.services.registry.get(chroot_name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {chroot_name}")
        source = Path(str(record.get("path", self.services.config_for(chroot_name).chroot_base)))
        if not source.exists():
            raise RuntimeError(f"missing chroot path: {source}")
        snapshot_name = (name or "snapshot").strip() or "snapshot"
        target = self.base_dir(chroot_name) / snapshot_name
        if target.exists():
            raise RuntimeError(f"snapshot already exists: {snapshot_name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=True)
        size_bytes = _directory_size(target)
        snapshot = self.services.registry.add_snapshot(
            name=snapshot_name,
            chroot_name=chroot_name,
            path=str(target),
            kind="copy",
            note=note,
            size_bytes=size_bytes,
            metadata={"source_path": str(source)},
        )
        self.services.audit().record(
            "snapshot.create",
            target=chroot_name,
            message=f"Created snapshot {snapshot_name}",
            metadata={"snapshot": snapshot_name},
        )
        return SnapshotActionResult(
            chroot_name=chroot_name,
            snapshot_name=snapshot_name,
            path=str(target),
            action="create",
            created_at=snapshot.created_at,
            next_steps=(
                f"Review snapshot files: {target}",
                f"Restore snapshot: /chroots/{chroot_name}/snapshots/{snapshot_name}/restore",
            ),
        )

    def restore(self, chroot_name: str, snapshot_name: str):
        snapshot = self.services.registry.get_snapshot_by_name(chroot_name, snapshot_name)
        target = self.services.config_for(chroot_name).chroot_base
        source = Path(snapshot.path)
        if not source.exists():
            raise RuntimeError(f"missing snapshot path: {source}")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, symlinks=True)
        self.services.audit().record(
            "snapshot.restore",
            target=chroot_name,
            message=f"Restored snapshot {snapshot_name}",
            metadata={"snapshot": snapshot_name},
        )
        return SnapshotActionResult(
            chroot_name=chroot_name,
            snapshot_name=snapshot_name,
            path=str(target),
            action="restore",
            created_at=snapshot.created_at,
            next_steps=(
                f"Start chroot: chrootctl --name {chroot_name} start --login",
                f"Review logs: chrootctl --name {chroot_name} logs --all",
            ),
        )

    def export(self, chroot_name: str, snapshot_name: str, *, archive: Path | None = None):
        snapshot = self.services.registry.get_snapshot_by_name(chroot_name, snapshot_name)
        source = Path(snapshot.path)
        if not source.exists():
            raise RuntimeError(f"missing snapshot path: {source}")
        target_archive = (archive or (source.parent / f"{snapshot_name}.tar.gz")).expanduser()
        target_archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target_archive, "w:gz") as handle:
            handle.add(source, arcname=source.name)
        self.services.audit().record(
            "snapshot.export",
            target=chroot_name,
            message=f"Exported snapshot {snapshot_name}",
            metadata={"snapshot": snapshot_name, "archive": str(target_archive)},
        )
        return SnapshotActionResult(
            chroot_name=chroot_name,
            snapshot_name=snapshot_name,
            path=str(source),
            action="export",
            created_at=snapshot.created_at,
            exported_archive=str(target_archive),
            next_steps=(f"Archive ready: {target_archive}",),
        )
