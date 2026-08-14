from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..bridge.protocol import serialize_value
from ..errors import AppError
from .context import ServiceContainer
from .storage_safety import contains_path, require_contained


_ARTIFACT_TTL_SECONDS: dict[str, int] = {
    "staged-import": 24 * 60 * 60,
    "chroot-export": 7 * 24 * 60 * 60,
    "checksum": 7 * 24 * 60 * 60,
    "support-bundle": 3 * 24 * 60 * 60,
    "module-archive": 7 * 24 * 60 * 60,
    "debug-evidence": 3 * 24 * 60 * 60,
    "temporary": 24 * 60 * 60,
}


def managed_transfer_root(*, create: bool = True) -> Path:
    """Return the single managed transfer/artifact root shared by Python and Android."""
    override = os.environ.get("CHROOTCTL_TRANSFER_DIR")
    if override:
        path = Path(override)
    else:
        android_tmp = Path("/data/local/tmp")
        if android_tmp.exists() and os.access(android_tmp, os.W_OK):
            path = android_tmp / "chrootctl-transfer"
        else:
            path = Path(tempfile.gettempdir()) / "chrootctl-transfer"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def managed_transfer_archive(name: str, suffix: str = "tar.zst", *, create_root: bool = True) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in name).strip("._-") or "chroot"
    return managed_transfer_root(create=create_root) / f"{safe}.{suffix}"


def _infer_artifact_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".sha256"):
        return "checksum"
    if "support" in name:
        return "support-bundle"
    if "debug" in name or "evidence" in name:
        return "debug-evidence"
    if "magisk" in name or "module" in name:
        return "module-archive"
    if name.endswith((".tar.zst", ".tar.zst.enc", ".tzst", ".tzst.enc")):
        return "staged-import"
    return "temporary"


def _artifact_payload(row: dict[str, Any], path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "artifactId": str(row.get("artifact_id") or ""),
        "artifact_id": str(row.get("artifact_id") or ""),
        "name": path.name,
        "path": str(path),
        "kind": str(row.get("kind") or "temporary"),
        "target": str(row.get("target") or ""),
        "size_bytes": int(stat.st_size),
        "sizeBytes": int(stat.st_size),
        "modified_at": float(stat.st_mtime),
        "modifiedAt": float(stat.st_mtime),
        "createdAt": float(row.get("created_at") or stat.st_mtime),
        "expiresAt": row.get("expires_at"),
        "managed": True,
        "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    }


class TransferService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def _managed_path(self, path: Path | str) -> Path:
        root = managed_transfer_root()
        candidate = Path(path).expanduser().resolve()
        return require_contained(root, candidate, label="managed transfer artifact")

    def register_artifact(
        self,
        path: Path | str,
        *,
        kind: str | None = None,
        target: str = "",
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        candidate = Path(path).expanduser().resolve()
        root = managed_transfer_root().resolve()
        if not contains_path(root, candidate) or not candidate.is_file():
            return None
        artifact_kind = kind or _infer_artifact_kind(candidate)
        effective_ttl = _ARTIFACT_TTL_SECONDS.get(artifact_kind, _ARTIFACT_TTL_SECONDS["temporary"]) if ttl_seconds is None else ttl_seconds
        return self.services.registry.register_artifact(
            path=str(candidate),
            kind=artifact_kind,
            target=target,
            size_bytes=int(candidate.stat().st_size),
            ttl_seconds=effective_ttl,
            metadata=metadata,
        )

    def _remove_registered_artifact(self, row: dict[str, Any]) -> bool:
        artifact_id = str(row.get("artifact_id") or "")
        path = self._managed_path(str(row.get("path") or ""))
        removed = False
        if path.exists() and path.is_file():
            path.unlink()
            removed = True
        if artifact_id:
            self.services.registry.delete_artifact(artifact_id)
        return removed

    def _reconcile_artifacts(self) -> None:
        root = managed_transfer_root().resolve()
        now = time.time()
        rows = self.services.registry.list_artifacts(include_expired=True, limit=5000)
        known_paths = {str(Path(str(row.get("path") or "")).expanduser().resolve()): row for row in rows if row.get("path")}

        for resolved_path, row in tuple(known_paths.items()):
            path = Path(resolved_path)
            artifact_id = str(row.get("artifact_id") or "")
            if not contains_path(root, path) or not path.is_file():
                if artifact_id:
                    self.services.registry.delete_artifact(artifact_id)
                continue
            expires_at = row.get("expires_at")
            if expires_at is not None and float(expires_at) <= now:
                self._remove_registered_artifact(row)

        # Files can arrive through the Android Binder descriptor path, so discover
        # and index unmanaged files using the conservative staged/temp policy.
        for entry in root.iterdir():
            if not entry.is_file():
                continue
            resolved = str(entry.resolve())
            row = self.services.registry.artifact_by_path(resolved)
            if row is None:
                self.register_artifact(entry, kind=_infer_artifact_kind(entry))

    def preview_export(self, *, name: str, archive: str | None = None) -> dict[str, Any]:
        return self.services.preview().export(name=name, archive=archive)

    def export(self, *, name: str, archive: Path | None = None, password: str | None = None):
        result = self.services.chroots().export(name, archive=archive, password=password)
        self.register_artifact(result.archive, kind="chroot-export", target=name, metadata={"encrypted": bool(password)})
        if result.checksum_path is not None:
            self.register_artifact(result.checksum_path, kind="checksum", target=name, metadata={"for": str(result.archive)})
        return result

    def import_archive(self, *, archive: Path, name: str | None = None, conflict: str = "rename", password: str | None = None, post_import: str = "register"):
        return self.services.chroots().import_archive(archive, name=name, conflict=conflict, password=password, post_import=post_import)

    def preview_import(self, *, archive: str, name: str | None = None, conflict: str = "rename", password: str | None = None) -> dict[str, Any]:
        self.register_artifact(archive, kind="staged-import")
        return self.services.preview().import_(archive=archive, name=name, conflict=conflict, password=password)

    def preview_delete(self, *, name: str) -> dict[str, Any]:
        return self.services.preview().delete(name=name)

    def preview_upgrade(self, *, name: str) -> dict[str, Any]:
        return self.services.preview().upgrade(name=name)

    def inspect(self, archive: str, *, password: str | None = None) -> dict[str, Any]:
        self.register_artifact(archive, kind="staged-import")
        inspection = self.services.chroots().inspect_archive(Path(archive), password=password)
        return serialize_value(inspection)

    def temp_state(self) -> dict[str, Any]:
        self._reconcile_artifacts()
        directory = managed_transfer_root().resolve()
        items: list[dict[str, Any]] = []
        for row in self.services.registry.list_artifacts(include_expired=False, limit=5000):
            raw_path = str(row.get("path") or "")
            if not raw_path:
                continue
            path = Path(raw_path).expanduser().resolve()
            if not contains_path(directory, path) or not path.is_file():
                continue
            items.append(_artifact_payload(row, path))
        items.sort(key=lambda item: float(item.get("modified_at") or 0), reverse=True)
        total_bytes = sum(int(item["size_bytes"]) for item in items)
        return {
            "directory": str(directory),
            "managedRoot": str(directory),
            "androidDescriptorRoot": "/data/local/tmp/chrootctl-transfer",
            "retentionPolicy": {kind: seconds for kind, seconds in sorted(_ARTIFACT_TTL_SECONDS.items())},
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
            "retentionPolicy": {kind: seconds for kind, seconds in sorted(_ARTIFACT_TTL_SECONDS.items())},
        }

    def delete_temp(self, *, artifact_id: str | None = None, path: str | None = None, delete_all: bool = False) -> dict[str, Any]:
        payload = self.temp_state()
        removed = 0
        if delete_all:
            for item in list(payload["items"]):
                row_id = str(item.get("artifactId") or item.get("artifact_id") or "")
                if not row_id:
                    continue
                try:
                    row = self.services.registry.get_artifact(row_id)
                except KeyError:
                    continue
                removed += int(self._remove_registered_artifact(row))
        elif artifact_id:
            try:
                row = self.services.registry.get_artifact(artifact_id)
            except KeyError as exc:
                raise AppError(
                    code="unknown_artifact_id",
                    title="Unknown transfer artifact",
                    message="The requested managed artifact no longer exists.",
                    status_code=404,
                ) from exc
            removed = int(self._remove_registered_artifact(row))
        elif path:
            target = self._managed_path(path)
            row = self.services.registry.artifact_by_path(str(target))
            if row is None:
                raise AppError(
                    code="unknown_temp_path",
                    title="Unknown transfer artifact",
                    message="The requested path is not registered as a managed transfer artifact.",
                    status_code=404,
                )
            removed = int(self._remove_registered_artifact(row))
        return {"removed": removed, **self.temp_state()}
