
from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from ..deps import get_jobs, get_services, get_templates, resolve_log_path

router = APIRouter(prefix="/transfer", tags=["transfer"])


def _submit_job(jobs, **kwargs):
    try:
        return jobs.submit(**kwargs)
    except TypeError:
        kwargs.pop("retry", None)
        return jobs.submit(**kwargs)

_TRANSFER_MAX_AGE_SECONDS = 60 * 60 * 24


def _job_redirect(job_id: str, *, toast: str = "Job queued") -> RedirectResponse:
    return RedirectResponse(url=f"/jobs/{job_id}?toast={toast.replace(' ', '+')}&toast_kind=ok", status_code=303)


@router.get("")
def transfer_page(
    request: Request,
    services=Depends(get_services),
    templates=Depends(get_templates),
    jobs=Depends(get_jobs),
    archive: str | None = None,
):
    _cleanup_transfer_dir()
    inspection = None
    archive_value = archive or ""
    if archive:
        try:
            inspection = _inspect_archive(services, Path(archive))
        except Exception as exc:
            inspection = {"error": str(exc)}
    return templates.TemplateResponse(
        request,
        "transfer.html",
        {
            "page_title": "Transfer",
            "chroots": services.chroots().list(),
            "inspection": inspection,
            "archive_value": archive_value,
            "cross_arch_state": _cross_arch_state(services),
            "foreign_arch_advisories": _foreign_arch_advisories(services),
            "recent_transfer_jobs": _recent_transfer_jobs(jobs),
            "transfer_temp_state": _transfer_temp_state(services),
        },
    )


@router.get("/temp")
def transfer_temp_listing(services=Depends(get_services)) -> dict[str, object]:
    _cleanup_transfer_dir()
    state = services.transfer().temp_state()
    return {
        "items": state["items"],
        "count": state["count"],
        "total_bytes": state["total_bytes"],
        "max_age_seconds": _TRANSFER_MAX_AGE_SECONDS,
        "runtime_mode": services.lifecycle().status().get("mode", {}),
    }


@router.get("/download/{name}")
def download_archive(name: str, password: str | None = None, services=Depends(get_services)):
    _cleanup_transfer_dir()
    export_dir = _transfer_upload_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    archive_path = export_dir / f"{name.strip()}.tar.zst"
    result = services.transfer().export(name.strip(), archive=archive_path, password=password)
    final_path = Path(getattr(result, "archive", archive_path)).expanduser().resolve()
    return FileResponse(path=final_path, media_type="application/zstd", filename=final_path.name)


@router.post("/inspect")
def inspect_archive(
    request: Request,
    archive: str = Form(...),
    password: str = Form(""),
    services=Depends(get_services),
    templates=Depends(get_templates),
    jobs=Depends(get_jobs),
):
    _cleanup_transfer_dir()
    archive_path = archive.strip()
    inspection = None
    error = None
    if archive_path:
        try:
            inspection = _inspect_archive(services, Path(archive_path), password=password.strip() or None)
        except Exception as exc:
            error = str(exc)
    return templates.TemplateResponse(
        request,
        "transfer.html",
        {
            "page_title": "Transfer",
            "chroots": services.chroots().list(),
            "inspection": inspection or ({"error": error} if error else None),
            "archive_value": archive_path,
            "cross_arch_state": _cross_arch_state(services),
            "foreign_arch_advisories": _foreign_arch_advisories(services),
            "recent_transfer_jobs": _recent_transfer_jobs(jobs),
            "transfer_temp_state": _transfer_temp_state(services),
        },
        status_code=200 if inspection or not error else 400,
    )


@router.post("/inspect-upload")
async def inspect_uploaded_archive(
    request: Request,
    archive_file: UploadFile = File(...),
    password: str = Form(""),
    services=Depends(get_services),
    templates=Depends(get_templates),
    jobs=Depends(get_jobs),
):
    _cleanup_transfer_dir()
    uploaded_path = await _save_upload(archive_file)
    inspection = None
    error = None
    try:
        inspection = _inspect_archive(services, uploaded_path, password=password.strip() or None)
    except Exception as exc:
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "transfer.html",
        {
            "page_title": "Transfer",
            "chroots": services.chroots().list(),
            "inspection": inspection or ({"error": error} if error else None),
            "archive_value": str(uploaded_path),
            "cross_arch_state": _cross_arch_state(services),
            "foreign_arch_advisories": _foreign_arch_advisories(services),
            "recent_transfer_jobs": _recent_transfer_jobs(jobs),
            "transfer_temp_state": _transfer_temp_state(services),
        },
        status_code=200 if inspection or not error else 400,
    )


@router.post("/export")
def export_archive(
    name: str = Form(...),
    archive: str = Form(""),
    password: str = Form(""),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    _cleanup_transfer_dir()
    target = name.strip()
    archive_path = Path(archive.strip()).expanduser() if archive.strip() else None
    job = _submit_job(jobs, 
        kind="chroot-export",
        title=f"Export chroot {target}",
        target_name=target,
        log_path=resolve_log_path(services, name=target),
        retry={"action": "transfer.export", "payload": {"name": target, "archive": str(archive_path), "password": password.strip() or None}, "href": f"/transfer?archive={archive_path}", "label": "Retry export"},
        runner=lambda progress: _run_export(services, name=target, archive=archive_path, password=password.strip() or None, progress=progress),
    )
    return _job_redirect(job.job_id, toast="Export queued")


@router.post("/import")
def import_archive(
    archive: str = Form(...),
    import_name: str = Form(""),
    conflict: str = Form("rename"),
    password: str = Form(""),
    post_import: str = Form("register"),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    _cleanup_transfer_dir()
    archive_path = Path(archive.strip()).expanduser()
    target_name = import_name.strip() or None
    job = _submit_job(jobs, 
        kind="chroot-import",
        title=f"Import archive {archive_path.name}",
        target_name=target_name,
        log_path=resolve_log_path(services, name=target_name),
        retry={"action": "transfer.import", "payload": {"archive": str(archive_path), "name": target_name, "conflict": conflict, "password": password.strip() or None, "post_import": post_import}, "href": f"/transfer?archive={archive_path}", "label": "Retry import"},
        runner=lambda progress: _run_import(services, archive=archive_path, name=target_name, conflict=conflict, password=password.strip() or None, post_import=post_import, progress=progress),
    )
    return _job_redirect(job.job_id, toast="Import queued")


@router.post("/import-upload")
async def import_uploaded_archive(
    import_name: str = Form(""),
    conflict: str = Form("rename"),
    archive_file: UploadFile = File(...),
    password: str = Form(""),
    post_import: str = Form("register"),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    _cleanup_transfer_dir()
    uploaded_path = await _save_upload(archive_file)
    target_name = import_name.strip() or None
    job = _submit_job(jobs, 
        kind="chroot-import",
        title=f"Import archive {uploaded_path.name}",
        target_name=target_name,
        log_path=resolve_log_path(services, name=target_name),
        retry={"action": "transfer.import", "payload": {"archive": str(uploaded_path), "name": target_name, "conflict": conflict, "password": password.strip() or None, "post_import": post_import}, "href": f"/transfer?archive={uploaded_path}", "label": "Retry import"},
        runner=lambda progress: _run_import(services, archive=uploaded_path, name=target_name, conflict=conflict, password=password.strip() or None, post_import=post_import, progress=progress),
    )
    return _job_redirect(job.job_id, toast="Import queued")


@router.post("/temp/delete")
def delete_temp_archive(path: str = Form(...)):
    candidate = Path(path).expanduser().resolve()
    transfer_dir = _transfer_upload_dir().resolve()
    if transfer_dir not in candidate.parents:
        return RedirectResponse(url="/transfer?toast=Invalid+archive+path&toast_kind=bad", status_code=303)
    if candidate.exists() and candidate.is_file():
        candidate.unlink()
        checksum_path = candidate.with_name(f"{candidate.name}.sha256")
        if checksum_path.exists():
            checksum_path.unlink()
    return RedirectResponse(url="/transfer?toast=Temp+archive+deleted&toast_kind=ok", status_code=303)


@router.post("/temp/clear")
def clear_temp_archives():
    transfer_dir = _transfer_upload_dir()
    if transfer_dir.exists():
        for item in list(transfer_dir.iterdir()):
            if item.is_file():
                item.unlink()
    return RedirectResponse(url="/transfer?toast=Temp+archives+cleared&toast_kind=ok", status_code=303)


def _run_export(services, *, name: str, archive: Path | None, password: str | None, progress):
    progress("Exporting chroot to tar.zst")
    return services.transfer().export(name, archive=archive, password=password)


def _run_import(services, *, archive: Path, name: str | None, conflict: str, password: str | None, post_import: str, progress):
    progress("Importing tar.zst archive")
    return services.transfer().import_archive(archive, name=name, conflict=conflict, password=password, post_import=post_import)


def _cross_arch_state(services) -> dict[str, object]:
    try:
        return services.system().cross_arch_state()
    except Exception:
        runner = services.runtime_for().runner
        host_arch = runner.host_arch()
        return {"host_arch": host_arch, "targets": []}



def _inspect_archive(services, archive: Path, password: str | None = None):
    transfer = services.transfer()
    if hasattr(transfer, "inspect"):
        return transfer.inspect(str(archive))
    archive_path = archive.expanduser().resolve()
    source_name = archive_path.name.removesuffix(".tar.zst").replace(".tar", "")
    return {
        "archive": str(archive_path),
        "source_name": source_name,
        "suggested_name": source_name,
        "path_name": source_name,
        "distro": "unknown",
        "arch": "unknown",
        "release_name": "",
        "version": "",
        "phase": "extract",
        "installed": False,
        "metadata": {},
        "size_bytes": archive_path.stat().st_size if archive_path.exists() else 0,
        "created_at": "",
        "checksum": None,
        "checksum_path": None,
        "checksum_verified": None,
        "target_exists": False,
        "conflict_strategy_options": ("rename", "overwrite"),
    }


def _recent_transfer_jobs(jobs) -> list[dict[str, object]]:
    try:
        snapshots = jobs.list_recent(limit=6, tail=5)
    except Exception:
        return []
    items: list[dict[str, object]] = []
    for snapshot in snapshots:
        if snapshot.kind not in {"chroot-export", "chroot-import"}:
            continue
        items.append(
            {
                "job_id": snapshot.job_id,
                "kind": snapshot.kind,
                "title": snapshot.title,
                "state": snapshot.state,
                "progress_text": snapshot.progress_text,
                "target_name": snapshot.target_name,
                "log_lines": snapshot.log_lines,
                "error": snapshot.error,
                "result_payload": snapshot.result_payload,
            }
        )
    return items


def _transfer_temp_state(services=None) -> dict[str, object]:
    if services is not None and hasattr(services, "transfer"):
        state = services.transfer().temp_state()
        state["files"] = state.get("items", [])[:12]
        state["items"] = state.get("items", [])[:12]
        state["path"] = state.get("directory", state.get("path", ""))
        return state
    transfer_dir = _transfer_upload_dir()
    if not transfer_dir.exists():
        return {"path": str(transfer_dir), "files": [], "items": [], "count": 0, "total_bytes": 0}
    files = sorted(({"name": item.name, "path": str(item), "size": item.stat().st_size, "modified_at": item.stat().st_mtime} for item in transfer_dir.iterdir() if item.is_file()), key=lambda item: item["modified_at"], reverse=True)
    total_bytes = sum(int(item["size"]) for item in files)
    return {"path": str(transfer_dir), "files": files[:12], "items": files[:12], "count": len(files), "total_bytes": total_bytes}


def _transfer_upload_dir() -> Path:
    return Path(tempfile.gettempdir()) / "chrootctl-webui-transfer"


def _cleanup_transfer_dir(*, max_age_seconds: int = _TRANSFER_MAX_AGE_SECONDS) -> None:
    transfer_dir = _transfer_upload_dir()
    if not transfer_dir.exists():
        return
    cutoff = time.time() - max_age_seconds
    for item in transfer_dir.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink()
        except FileNotFoundError:
            continue


async def _save_upload(upload: UploadFile) -> Path:
    filename = Path(upload.filename or "upload.tar.zst").name
    target_dir = _transfer_upload_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    with target_path.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    await upload.close()
    return target_path


def _foreign_arch_advisories(services) -> list[dict[str, str]]:
    try:
        return services.system().foreign_arch_advisories()
    except Exception:
        return []
