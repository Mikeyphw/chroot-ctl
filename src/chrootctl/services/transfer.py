
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from ..errors import AppError
from ..bridge.protocol import serialize_value
from .context import ServiceContainer


def managed_transfer_root() -> Path:
    """Return the single managed transfer/artifact root shared by Python and Android.

    Android root-service exports copy only from this directory. On Android we prefer
    /data/local/tmp/chrootctl-transfer; on desktop/tests we fall back to the Python
    temp directory unless CHROOTCTL_TRANSFER_DIR is set.
    """
    override = os.environ.get("CHROOTCTL_TRANSFER_DIR")
    if override:
        path = Path(override)
    else:
        android_tmp = Path("/data/local/tmp")
        if android_tmp.exists() and os.access(android_tmp, os.W_OK):
            path = android_tmp / "chrootctl-transfer"
        else:
            path = Path(tempfile.gettempdir()) / "chrootctl-transfer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def managed_transfer_archive(name: str, suffix: str = "tar.zst") -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in name).strip("._-") or "chroot"
    return managed_transfer_root() / f"{safe}.{suffix}"


def _contains_path(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class TransferService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def preview_export(self, *, name: str, archive: str | None = None) -> dict[str, Any]:
        return self.services.preview().export(name=name, archive=archive)

    def export(self, *, name: str, archive: Path | None = None, password: str | None = None):
        return self.services.chroots().export(name, archive=archive, password=password)

    def import_archive(self, *, archive: Path, name: str | None = None, conflict: str = "rename", password: str | None = None, post_import: str = "register"):
        return self.services.chroots().import_archive(archive, name=name, conflict=conflict, password=password, post_import=post_import)

    def preview_import(self, *, archive: str, name: str | None = None, conflict: str = "rename") -> dict[str, Any]:
        return self.services.preview().import_(archive=archive, name=name, conflict=conflict)

    def preview_delete(self, *, name: str) -> dict[str, Any]:
        return self.services.preview().delete(name=name)

    def preview_upgrade(self, *, name: str) -> dict[str, Any]:
        return self.services.preview().upgrade(name=name)

    def inspect(self, archive: str) -> dict[str, Any]:
        inspection = self.services.chroots().inspect_archive(Path(archive))
        return serialize_value(inspection)

    def temp_state(self) -> dict[str, Any]:
        directory = managed_transfer_root()
        items: list[dict[str, Any]] = []
        for entry in sorted(directory.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if entry.is_file():
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size_bytes": int(stat.st_size),
                    "modified_at": float(stat.st_mtime),
                    "managed": True,
                })
        total_bytes = sum(int(item["size_bytes"]) for item in items)
        return {
            "directory": str(directory),
            "managedRoot": str(directory),
            "androidDescriptorRoot": "/data/local/tmp/chrootctl-transfer",
            "count": len(items),
            "total_bytes": total_bytes,
            "items": items,
        }

    def artifact_root(self) -> dict[str, Any]:
        root = managed_transfer_root()
        return {
            "path": str(root),
            "managedRoot": str(root),
            "androidDescriptorRoot": "/data/local/tmp/chrootctl-transfer",
            "exists": root.exists(),
            "writable": root.exists() and root.is_dir() and os.access(root, os.W_OK),
        }

    def delete_temp(self, *, path: str | None = None, delete_all: bool = False) -> dict[str, Any]:
        payload = self.temp_state()
        removed = 0
        root_dir = managed_transfer_root().resolve()
        if delete_all:
            for item in payload["items"]:
                target = Path(str(item["path"])).resolve()
                if target.exists() and _contains_path(root_dir, target):
                    target.unlink()
                    removed += 1
        elif path:
            target = Path(path).expanduser().resolve()
            if not _contains_path(root_dir, target):
                raise AppError(
                    code="invalid_temp_path",
                    title="Invalid temp archive path",
                    message="The requested temp archive is outside the managed transfer cache.",
                    status_code=400,
                )
            if target.exists():
                target.unlink()
                removed = 1
        return {"removed": removed, **self.temp_state()}
