
from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..errors import AppError
from ..web.serialize import serialize_value
from .context import ServiceContainer


def _transfer_temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "chrootctl-transfer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _upload_session_dir() -> Path:
    path = _transfer_temp_dir() / ".uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_upload_name(name: str) -> str:
    candidate = Path(name or "upload.tar.zst").name.strip() or "upload.tar.zst"
    return candidate.replace("/", "_").replace("\\", "_")


def _session_meta_path(session_id: str) -> Path:
    return _upload_session_dir() / f"{session_id}.json"


def _session_part_path(session_id: str) -> Path:
    return _upload_session_dir() / f"{session_id}.part"


def _session_final_path(session_id: str, filename: str) -> Path:
    return _transfer_temp_dir() / f"{session_id}-{_safe_upload_name(filename)}"


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()



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
        chroots = self.services.chroots()
        if hasattr(chroots, "inspect_archive"):
            inspection = chroots.inspect_archive(Path(archive))
        else:
            archive_path = Path(archive).expanduser().resolve()
            fallback_name = archive_path.name.removesuffix(".tar.zst").replace(".tar", "")
            inspection = {
                "archive": str(archive_path),
                "source_name": fallback_name,
                "suggested_name": fallback_name,
                "path_name": fallback_name,
                "distro": "unknown",
                "arch": "unknown",
                "release_name": "",
                "version": "",
                "phase": "extract",
                "installed": False,
                "metadata": {},
            }
        return serialize_value(inspection)

    def temp_state(self) -> dict[str, Any]:
        directory = _transfer_temp_dir()
        items = []
        for entry in sorted(directory.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if entry.is_file():
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size_bytes": int(stat.st_size),
                    "modified_at": float(stat.st_mtime),
                })
        total_bytes = sum(int(item["size_bytes"]) for item in items)
        return {"directory": str(directory), "count": len(items), "total_bytes": total_bytes, "items": items}


    def start_upload(self, *, filename: str, total_size: int | None = None, content_type: str | None = None) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        safe_name = _safe_upload_name(filename)
        meta = {
            "session_id": session_id,
            "filename": safe_name,
            "content_type": content_type or "application/octet-stream",
            "total_size": int(total_size) if total_size is not None else None,
            "received_bytes": 0,
            "complete": False,
            "final_path": str(_session_final_path(session_id, safe_name)),
            "part_path": str(_session_part_path(session_id)),
        }
        _session_meta_path(session_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        _session_part_path(session_id).write_bytes(b"")
        return meta

    def upload_status(self, session_id: str) -> dict[str, Any]:
        meta_path = _session_meta_path(session_id)
        if not meta_path.exists():
            raise AppError(
                code="upload_session_not_found",
                title="Upload session not found",
                message="The requested upload session does not exist.",
                status_code=404,
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        part_path = Path(str(meta["part_path"]))
        meta["received_bytes"] = int(part_path.stat().st_size) if part_path.exists() else 0
        meta["resumable"] = not bool(meta.get("complete"))
        return meta

    def upload_chunk(self, *, session_id: str, offset: int, data: bytes) -> dict[str, Any]:
        meta = self.upload_status(session_id)
        if bool(meta.get("complete")):
            raise AppError(
                code="upload_already_complete",
                title="Upload already complete",
                message="This upload session has already been finalized.",
                status_code=409,
            )
        part_path = Path(str(meta["part_path"]))
        current_size = int(part_path.stat().st_size) if part_path.exists() else 0
        if offset != current_size:
            raise AppError(
                code="upload_offset_mismatch",
                title="Upload offset mismatch",
                message="The next upload chunk does not match the current resume offset.",
                details={"expected_offset": current_size, "received_offset": offset},
                hints=["Query the upload session status and resume from the reported received_bytes value."],
                retryable=True,
                status_code=409,
            )
        with part_path.open("ab") as handle:
            handle.write(data)
        meta["received_bytes"] = int(part_path.stat().st_size)
        _session_meta_path(session_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    def complete_upload(self, *, session_id: str, expected_size: int | None = None) -> dict[str, Any]:
        meta = self.upload_status(session_id)
        part_path = Path(str(meta["part_path"]))
        received = int(meta["received_bytes"])
        total_size = meta.get("total_size")
        expected = int(expected_size) if expected_size is not None else (int(total_size) if total_size is not None else None)
        if expected is not None and received != expected:
            raise AppError(
                code="upload_incomplete",
                title="Upload is incomplete",
                message="The upload cannot be finalized until all expected bytes are present.",
                details={"expected_size": expected, "received_bytes": received},
                retryable=True,
                status_code=409,
            )
        final_path = Path(str(meta["final_path"]))
        if final_path.exists():
            final_path.unlink()
        part_path.replace(final_path)
        checksum = _sha256_file(final_path)
        checksum_path = final_path.with_name(f"{final_path.name}.sha256")
        checksum_path.write_text(f"{checksum}  {final_path.name}\n", encoding="utf-8")
        meta["received_bytes"] = int(final_path.stat().st_size)
        meta["complete"] = True
        meta["resumable"] = False
        meta["checksum"] = checksum
        meta["checksum_path"] = str(checksum_path)
        _session_meta_path(session_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self.services.audit().record(
            "transfer.upload",
            target=meta["filename"],
            message=f"Uploaded {meta['filename']}",
            metadata={"bytes": str(meta["received_bytes"]), "session_id": session_id},
        )
        return meta


    def abort_upload(self, *, session_id: str) -> dict[str, Any]:
        meta = self.upload_status(session_id)
        part_path = Path(str(meta.get("part_path") or ""))
        final_path = Path(str(meta.get("final_path") or ""))
        checksum_path = Path(str(meta.get("checksum_path") or "")) if meta.get("checksum_path") else None
        for candidate in (part_path, final_path, checksum_path):
            if candidate and str(candidate) and candidate.exists():
                candidate.unlink()
        meta_path = _session_meta_path(session_id)
        if meta_path.exists():
            meta_path.unlink()
        self.services.audit().record(
            "transfer.upload.abort",
            target=str(meta.get("filename") or session_id),
            message=f"Aborted upload {meta.get('filename') or session_id}",
            metadata={"session_id": session_id},
        )
        return {"aborted": True, "session_id": session_id}

    def delete_temp(self, *, path: str | None = None, delete_all: bool = False) -> dict[str, Any]:
        payload = self.temp_state()
        removed = 0
        if delete_all:
            for item in payload["items"]:
                target = Path(str(item["path"]))
                if target.exists():
                    target.unlink()
                    removed += 1
        elif path:
            target = Path(path).expanduser()
            root_dir = _transfer_temp_dir().resolve()
            resolved = target.resolve()
            if root_dir not in resolved.parents:
                raise AppError(
                    code="invalid_temp_path",
                    title="Invalid temp archive path",
                    message="The requested temp archive is outside the managed transfer cache.",
                    status_code=400,
                )
            if resolved.exists():
                resolved.unlink()
                removed = 1
        return {"removed": removed, **self.temp_state()}
