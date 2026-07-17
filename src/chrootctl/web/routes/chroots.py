from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import RedirectResponse

from ..deps import get_jobs, get_services, get_templates, resolve_log_path

router = APIRouter(prefix="/chroots", tags=["chroots"])


def _submit_job(jobs, **kwargs):
    try:
        return jobs.submit(**kwargs)
    except TypeError:
        kwargs.pop("retry", None)
        return jobs.submit(**kwargs)


def _job_redirect(job_id: str, *, toast: str = "Job queued") -> RedirectResponse:
    return RedirectResponse(url=f"/jobs/{job_id}?toast={toast.replace(' ', '+')}&toast_kind=ok", status_code=303)


def _bool_from_form(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"0", "false", "off", "no", ""}


@router.get("")
def list_chroots(
    request: Request,
    left: str | None = Query(default=None),
    right: str | None = Query(default=None),
    services=Depends(get_services),
    templates=Depends(get_templates),
):
    chroots = services.chroots().list()
    diff_result = None
    if left and right:
        try:
            diff_result = services.chroots().package_diff(left, right)
        except Exception as exc:
            diff_result = {"error": str(exc), "left": left, "right": right}
    return templates.TemplateResponse(
        request,
        "chroots.html",
        {
            "page_title": "Chroots",
            "chroots": chroots,
            "chroot_names": [item.name for item in chroots],
            "diff_result": diff_result,
        },
    )


@router.get("/{name}")
def show_chroot(name: str, request: Request, services=Depends(get_services), templates=Depends(get_templates)):
    return templates.TemplateResponse(
        request,
        "chroot_detail.html",
        {
            "page_title": f"Chroot · {name}",
            "chroot": services.chroots().get(name),
            "status_rows": services.system().status(name),
            "doctor_rows": services.system().doctor(name),
            "shell_command": f"chrootctl --name {name} start --login",
            "exec_command": f"chrootctl --name {name} exec -- command -v python3",
            "snapshots": _safe_snapshots(services, name),
        },
    )


@router.post("/{name}/start")
def start_chroot(name: str, services=Depends(get_services), jobs=Depends(get_jobs)):
    job = _submit_job(jobs, 
        kind="chroot-start",
        title=f"Start chroot {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        retry={"action": "chroot.start", "payload": {"name": name}, "label": "Retry start", "href": f"/chroots/{name}"},
        runner=lambda progress: _run_start(services, name=name, progress=progress),
    )
    return _job_redirect(job.job_id)


@router.post("/{name}/restart")
def restart_chroot(name: str, services=Depends(get_services), jobs=Depends(get_jobs)):
    job = _submit_job(jobs, 
        kind="chroot-restart",
        title=f"Restart chroot {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        retry={"action": "chroot.restart", "payload": {"name": name}, "label": "Retry restart", "href": f"/chroots/{name}"},
        runner=lambda progress: _run_restart(services, name=name, progress=progress),
    )
    return _job_redirect(job.job_id)


@router.post("/{name}/upgrade")
def upgrade_chroot(
    name: str,
    confirm_upgrade: str = Form(...),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    if not _bool_from_form(confirm_upgrade):
        raise HTTPException(status_code=400, detail="confirm the upgrade before continuing")
    job = _submit_job(jobs, 
        kind="chroot-upgrade",
        title=f"Upgrade chroot {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        retry={"action": "chroot.upgrade", "payload": {"name": name}, "label": "Retry upgrade", "href": f"/chroots/{name}"},
        runner=lambda progress: services.install().upgrade(name, progress=progress),
    )
    return _job_redirect(job.job_id)


@router.post("/{name}/rename")
def rename_chroot(
    name: str,
    new_name: str = Form(...),
    confirm_name: str = Form(...),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    normalized_name = new_name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    if confirm_name.strip() != name:
        raise HTTPException(status_code=400, detail=f"type the current chroot name to confirm rename: {name}")
    job = _submit_job(jobs, 
        kind="chroot-rename",
        title=f"Rename chroot {name} → {normalized_name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        runner=lambda progress: _run_rename(services, old_name=name, new_name=normalized_name, progress=progress),
    )
    return _job_redirect(job.job_id)


@router.post("/{name}/remove")
def remove_chroot(
    name: str,
    confirm_name: str = Form(...),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    if confirm_name.strip() != name:
        raise HTTPException(status_code=400, detail=f"type the chroot name to confirm removal: {name}")
    job = _submit_job(jobs, 
        kind="chroot-remove",
        title=f"Remove chroot {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        runner=lambda progress: _run_remove(services, name=name, progress=progress),
    )
    return _job_redirect(job.job_id)


@router.post("/{name}/snapshots")
def create_snapshot(
    name: str,
    snapshot_name: str = Form(""),
    note: str = Form(""),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    chosen = snapshot_name.strip() or "snapshot"
    job = _submit_job(jobs, 
        kind="snapshot-create",
        title=f"Snapshot {name}:{chosen}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        retry={"action": "snapshot.create", "payload": {"name": name, "snapshot_name": chosen, "note": note.strip()}, "href": f"/chroots/{name}", "label": "Retry snapshot"},
        runner=lambda progress: _run_snapshot_create(services, name=name, snapshot_name=chosen, note=note.strip(), progress=progress),
    )
    return _job_redirect(job.job_id, toast="Snapshot job queued")


@router.post("/{name}/snapshots/{snapshot_name}/restore")
def restore_snapshot(
    name: str,
    snapshot_name: str,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    job = _submit_job(jobs, 
        kind="snapshot-restore",
        title=f"Restore {name}:{snapshot_name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        retry={"action": "snapshot.create", "payload": {"name": name, "snapshot_name": chosen, "note": note.strip()}, "href": f"/chroots/{name}", "label": "Retry snapshot"},
        runner=lambda progress: _run_snapshot_restore(services, name=name, snapshot_name=snapshot_name, progress=progress),
    )
    return _job_redirect(job.job_id, toast="Restore job queued")


@router.post("/{name}/snapshots/{snapshot_name}/export")
def export_snapshot(
    name: str,
    snapshot_name: str,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    job = _submit_job(jobs, 
        kind="snapshot-export",
        title=f"Export snapshot {name}:{snapshot_name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        retry={"action": "snapshot.create", "payload": {"name": name, "snapshot_name": chosen, "note": note.strip()}, "href": f"/chroots/{name}", "label": "Retry snapshot"},
        runner=lambda progress: _run_snapshot_export(services, name=name, snapshot_name=snapshot_name, progress=progress),
    )
    return _job_redirect(job.job_id, toast="Snapshot export queued")



def _run_snapshot_create(services, *, name: str, snapshot_name: str, note: str, progress):
    progress({"phase": "snapshot", "message": "Copying chroot into snapshot", "percent": 25})
    result = services.snapshots().create(name, name=snapshot_name, note=note)
    progress({"phase": "snapshot", "message": "Snapshot created", "percent": 100})
    return result


def _run_snapshot_restore(services, *, name: str, snapshot_name: str, progress):
    progress({"phase": "restore", "message": "Restoring snapshot into chroot", "percent": 30})
    result = services.snapshots().restore(name, snapshot_name)
    progress({"phase": "restore", "message": "Snapshot restored", "percent": 100})
    return result


def _run_snapshot_export(services, *, name: str, snapshot_name: str, progress):
    progress({"phase": "export", "message": "Packaging snapshot archive", "percent": 35})
    result = services.snapshots().export(name, snapshot_name)
    progress({"phase": "export", "message": "Snapshot archive ready", "percent": 100})
    return result


def _run_start(services, *, name: str, progress) -> object:
    progress("Starting chroot session")
    return services.chroots().start(name)


def _run_restart(services, *, name: str, progress) -> object:
    progress("Restarting chroot session")
    return services.chroots().restart(name)


def _run_rename(services, *, old_name: str, new_name: str, progress) -> object:
    progress("Renaming chroot")
    return services.chroots().rename(old_name, new_name)


def _run_remove(services, *, name: str, progress) -> object:
    progress("Removing chroot")
    return services.chroots().remove(name)


def _safe_snapshots(services, name: str):
    try:
        return services.snapshots().list(chroot_name=name, limit=20)
    except Exception:
        return []
