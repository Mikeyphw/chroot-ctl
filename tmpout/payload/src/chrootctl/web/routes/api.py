from __future__ import annotations

from typing import Any
from pathlib import Path
import tempfile

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from ...errors import AppError, ErrorResponse
from ...models import InstallRequest
from ..deps import get_jobs, get_services, resolve_log_path
from ..serialize import serialize_value

router = APIRouter(prefix="/api", tags=["api"])


class InstallValidationRequest(BaseModel):
    distro: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    username: str | None = None
    preset: str | None = None
    profile: str | None = None
    desktop: str | None = None
    release: str | None = None
    version: str | None = None
    mirror: str | None = None
    tools: list[str] = Field(default_factory=list)
    addons: list[str] = Field(default_factory=list)
    repair: bool = False


class ActionRequest(BaseModel):
    action: str = Field(..., min_length=1)
    target: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorResponse


class ApiActionResponse(BaseModel):
    job_id: str | None = None
    status: str
    location: str | None = None
    result: dict[str, Any] | None = None


class TransferReadinessResponse(BaseModel):
    host_arch: str
    targets: list[dict[str, Any]]



class DoctorReadinessResponse(BaseModel):
    host_arch: str
    checks: list[dict[str, Any]]
    summary: dict[str, int]
    advisories: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)


class JobListResponse(BaseModel):
    items: list[dict[str, Any]]
    active: int
    terminal: int


class JobLogResponse(BaseModel):
    job_id: str
    path: str | None = None
    exists: bool
    tail: int
    lines: list[str] = Field(default_factory=list)
    download_url: str | None = None


class EventListResponse(BaseModel):
    items: list[dict[str, Any]]


class SupportBundleApiResponse(BaseModel):
    archive: str
    included: list[str] = Field(default_factory=list)


class SnapshotListResponse(BaseModel):
    items: list[dict[str, Any]]


class JobRetryRequest(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


class RegistryRepairResponse(BaseModel):
    scanned_paths: int
    missing_records: list[str] = Field(default_factory=list)
    missing_paths: list[str] = Field(default_factory=list)
    mismatched_paths: list[str] = Field(default_factory=list)
    repaired_records: list[str] = Field(default_factory=list)
    removed_records: list[str] = Field(default_factory=list)
    preview: bool = True
    next_steps: list[str] = Field(default_factory=list)


class RegistryRepairPlanPreviewResponse(BaseModel):
    ok: bool = False
    summary: dict[str, Any] = Field(default_factory=dict)
    selected: list[dict[str, Any]] = Field(default_factory=list)

class RegistryRepairDecision(BaseModel):
    item_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)


class RegistryRepairPlanRequest(BaseModel):
    decisions: list[RegistryRepairDecision] = Field(default_factory=list)


class SnapshotRecoveryResponse(BaseModel):
    snapshot: dict[str, Any] | None = None
    available: bool = False



class UploadInitRequest(BaseModel):
    filename: str = Field(..., min_length=1, examples=["ubuntu.tar.zst"])
    total_size: int | None = Field(default=None, ge=0, examples=[104857600])
    content_type: str | None = Field(default=None, examples=["application/zstd"])


class UploadSessionResponse(BaseModel):
    session_id: str
    filename: str
    content_type: str | None = None
    total_size: int | None = None
    received_bytes: int = 0
    complete: bool = False
    resumable: bool = True
    final_path: str
    part_path: str | None = None
    checksum: str | None = None
    checksum_path: str | None = None


class UploadAbortResponse(BaseModel):
    aborted: bool = True
    session_id: str


class UploadCompleteRequest(BaseModel):
    expected_size: int | None = Field(default=None, ge=0, examples=[104857600])


class JobEventResponse(BaseModel):
    job_id: str
    kind: str
    title: str
    state: str
    progress_text: str | None = None
    created_at: float | None = None
    started_at: float | None = None
    finished_at: float | None = None
    target_name: str | None = None
    complete: bool | None = None
    error: str | None = None
    log_lines: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    log_path: str | None = None
    log_download_url: str | None = None
    progress_detail: dict[str, Any] = Field(default_factory=dict)
    progress_events: list[dict[str, Any]] = Field(default_factory=list)
    result_payload: dict[str, Any] | list[Any] | str | int | float | bool | None = None


@router.get("/state", responses={500: {"model": ErrorEnvelope}})
def state(request: Request, services=Depends(get_services), jobs=Depends(get_jobs)) -> dict[str, Any]:
    security = request.app.state.web_security
    chroots = _chroot_summary(services)
    lifecycle = _lifecycle_status(services, host=security.bind_host, port=security.bind_port)
    recent_jobs = [job.to_event_payload() for job in jobs.list_recent(limit=5, tail=5)]
    last_error = next((job.error for job in jobs.list_recent(limit=20, tail=0) if job.error), None)
    return {
        "server": lifecycle,
        "module": lifecycle["module"],
        "python": lifecycle["python"],
        "chroots": chroots,
        "jobs": {
            "recent": recent_jobs,
            "active": sum(1 for job in jobs.list_recent(limit=100, tail=0) if not job.complete),
        },
        "last_error": last_error,
    }


@router.get("/install/options", responses={500: {"model": ErrorEnvelope}})
def install_options(services=Depends(get_services), distro: str | None = None, name: str | None = None) -> dict[str, Any]:
    install = services.install()
    defaults = install.wizard_defaults(name=name, distro=distro)
    return install.install_form_state(name=name, distro=distro)




@router.post("/install/validate", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def validate_install(payload: InstallValidationRequest, services=Depends(get_services)) -> dict[str, Any]:
    install_request = InstallRequest(
        distro=payload.distro,
        name=payload.name,
        username=(payload.username or "").strip(),
        preset=_optional_str(payload.preset),
        profile=_optional_str(payload.profile),
        desktop=_optional_str(payload.desktop),
        release=_optional_str(payload.release),
        version=_optional_str(payload.version),
        mirror=_optional_str(payload.mirror),
        tools=tuple(payload.tools),
        addons=tuple(payload.addons),
        repair=payload.repair,
    )
    result = services.install().validate_install_submission(install_request)
    if not result["ok"]:
        raise AppError(
            code="install_validation_failed",
            title="Install validation failed",
            message="The install request has blocking issues.",
            details={"blocking": result.get("blocking", []), "warnings": result.get("warnings", [])},
            hints=["Resolve the blocking issues and retry the install preview."],
            actions=[{"label": "Open install wizard", "href": "/install"}],
            retryable=True,
            status_code=400,
        )
    return result




@router.post("/install/preview", response_model=dict[str, Any], summary="Preview an install plan", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}, openapi_extra={"requestBody": {"content": {"application/json": {"example": {"distro": "ubuntu", "name": "androidos", "preset": "desktop", "username": "mike"}}}}})
def preview_install(payload: InstallValidationRequest, services=Depends(get_services)) -> dict[str, Any]:
    install_request = InstallRequest(
        distro=payload.distro,
        name=payload.name,
        username=(payload.username or "").strip(),
        preset=_optional_str(payload.preset),
        profile=_optional_str(payload.profile),
        desktop=_optional_str(payload.desktop),
        release=_optional_str(payload.release),
        version=_optional_str(payload.version),
        mirror=_optional_str(payload.mirror),
        tools=tuple(payload.tools),
        addons=tuple(payload.addons),
        repair=payload.repair,
    )
    result = services.install().preview_install(install_request)
    if not result["ok"]:
        raise AppError(
            code="install_preview_failed",
            title="Install preview failed",
            message="The install preview found blocking issues.",
            details={"blocking": result.get("blocking", []), "preview": result.get("preview", {})},
            hints=["Resolve the blocking issues and retry the install preview."],
            actions=[{"label": "Open install wizard", "href": "/install"}],
            retryable=True,
            status_code=400,
        )
    return result


@router.get("/transfer/preview/export", response_model=dict[str, Any], summary="Preview a chroot export", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}, openapi_extra={"parameters": [{"name":"name","in":"query","required":True,"schema":{"type":"string"},"example":"androidos"}]})
def preview_export(name: str = Query(..., min_length=1), archive: str | None = None, services=Depends(get_services)) -> dict[str, Any]:
    return services.transfer().preview_export(name=name.strip(), archive=archive)


@router.get("/transfer/preview/import", response_model=dict[str, Any], summary="Preview an archive import", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}, openapi_extra={"parameters": [{"name":"archive","in":"query","required":True,"schema":{"type":"string"},"example":"/sdcard/Download/androidos.tar.zst"}]})
def preview_import(archive: str = Query(..., min_length=1), name: str | None = None, conflict: str = Query("rename"), services=Depends(get_services)) -> dict[str, Any]:
    return services.transfer().preview_import(archive=archive, name=name, conflict=conflict)


@router.get("/transfer/preview/delete", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def preview_delete(name: str = Query(..., min_length=1), services=Depends(get_services)) -> dict[str, Any]:
    return services.transfer().preview_delete(name=name.strip())

@router.get("/install/preview/upgrade", response_model=dict[str, Any], summary="Preview a chroot upgrade", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}, openapi_extra={"parameters": [{"name":"name","in":"query","required":True,"schema":{"type":"string"},"example":"androidos"}]})
def preview_upgrade(name: str = Query(..., min_length=1), services=Depends(get_services)) -> dict[str, Any]:
    return services.transfer().preview_upgrade(name=name.strip())


@router.get("/transfer/temp", response_model=dict[str, Any], summary="List cached transfer artifacts", responses={500: {"model": ErrorEnvelope}})
def transfer_temp_state(services=Depends(get_services)) -> dict[str, Any]:
    return services.transfer().temp_state()


@router.delete("/transfer/temp", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def delete_transfer_temp(path: str | None = None, delete_all: bool = False, services=Depends(get_services)) -> dict[str, Any]:
    return services.transfer().delete_temp(path=path, delete_all=delete_all)


@router.get("/transfer/inspect", response_model=dict[str, Any], summary="Inspect an archive before import", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}, openapi_extra={"parameters": [{"name":"archive","in":"query","required":True,"schema":{"type":"string"},"example":"/sdcard/Download/androidos.tar.zst"}]})
def inspect_transfer_archive(archive: str, services=Depends(get_services)) -> dict[str, Any]:
    return services.transfer().inspect(archive)


@router.get("/transfer/readiness", response_model=TransferReadinessResponse, summary="Get transfer and foreign-arch readiness", responses={500: {"model": ErrorEnvelope}})
def transfer_readiness(services=Depends(get_services)) -> dict[str, Any]:
    return services.doctor().cross_arch_readiness()



@router.get("/doctor/host", response_model=DoctorReadinessResponse, summary="Run host readiness and doctor checks", responses={500: {"model": ErrorEnvelope}})
def doctor_host(services=Depends(get_services)) -> dict[str, Any]:
    return services.doctor().host_readiness()




@router.get("/chroots/diff", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def api_chroot_diff(
    left: str = Query(..., min_length=1),
    right: str = Query(..., min_length=1),
    services=Depends(get_services),
):
    return serialize_value(services.chroots().package_diff(left, right))


@router.post("/actions", response_model=ApiActionResponse, responses={400: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def actions(request: ActionRequest, services=Depends(get_services), jobs=Depends(get_jobs)) -> dict[str, Any]:
    action = request.action.strip().lower()
    target = (request.target or request.payload.get("name") or "").strip() or None
    if action in {"webui-start", "webui-stop", "webui-restart"}:
        lifecycle = _lifecycle_service(services)
        result = {
            "webui-start": lifecycle.start_webui,
            "webui-stop": lifecycle.stop_webui,
            "webui-restart": lifecycle.restart_webui,
        }[action]()
        return {"job_id": None, "status": "completed", "result": result}

    if action in {"start", "restart", "mount", "unmount", "status", "doctor", "logs"}:
        if not target:
            raise AppError(
                code="missing_target",
                title="Missing chroot target",
                message="A target chroot name is required for this action.",
                details={"action": action},
                hints=["Choose a chroot before submitting the action."],
                status_code=400,
            )
        job = jobs.submit(
            kind=f"chroot-{action}",
            title=f"{action.title()} {target}",
            target_name=target,
            log_path=resolve_log_path(services, name=target),
            runner=lambda progress: _run_chroot_action(services, action=action, target=target, progress=progress),
        )
        return {"job_id": job.job_id, "status": job.state, "location": f"/jobs/{job.job_id}"}

    if action == "install":
        install_request = _install_request_from_payload(request.payload)
        validation = services.install().validate_install_submission(install_request)
        if not validation["ok"]:
            raise AppError(
                code="install_validation_failed",
                title="Install validation failed",
                message="The install request has blocking issues.",
                details={"blocking": validation.get("blocking", []), "warnings": validation.get("warnings", [])},
                hints=["Resolve the blocking issues and retry the install."],
                actions=[{"label": "Open install wizard", "href": "/install"}],
                retryable=True,
                status_code=400,
            )
        job = jobs.submit(
            kind="install",
            title=f"Install {install_request.name}",
            target_name=install_request.name,
            log_path=resolve_log_path(services, name=install_request.name, username=install_request.username),
            runner=lambda progress: services.install().install(install_request, progress=progress),
        )
        return {"job_id": job.job_id, "status": job.state, "location": f"/jobs/{job.job_id}"}

    raise AppError(
        code="unsupported_action",
        title="Unsupported action",
        message=f"The requested action is not supported: {action}",
        details={"action": action},
        status_code=400,
    )



@router.get("/jobs", response_model=JobListResponse, responses={500: {"model": ErrorEnvelope}})
def list_jobs(
    jobs=Depends(get_jobs),
    kind: list[str] = Query(default=[]),
    limit: int = Query(12, ge=1, le=50),
    tail: int = Query(12, ge=0, le=500),
) -> dict[str, Any]:
    snapshots = jobs.list_recent(limit=limit, tail=tail)
    normalized = {item.strip().lower() for item in kind if item.strip()}
    if normalized:
        snapshots = [item for item in snapshots if item.kind.strip().lower() in normalized]
    items = [item.to_event_payload(log_download_url=f"/jobs/{item.job_id}/logs/download") for item in snapshots]
    return {
        "items": items,
        "active": sum(1 for item in snapshots if not item.complete),
        "terminal": sum(1 for item in snapshots if item.complete),
    }


@router.get("/jobs/{job_id}", response_model=JobEventResponse, responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def job_status(job_id: str, jobs=Depends(get_jobs), tail: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    try:
        return jobs.get(job_id, tail=tail).to_event_payload(log_download_url=f"/jobs/{job_id}/logs/download")
    except KeyError as exc:
        raise AppError(
            code="job_not_found",
            title="Job not found",
            message="The requested job does not exist.",
            details={"job_id": job_id},
            hints=["Refresh the jobs page and retry."],
            status_code=404,
        ) from exc


@router.get("/jobs/{job_id}/logs", response_model=JobLogResponse, responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def job_logs(job_id: str, jobs=Depends(get_jobs), tail: int = Query(200, ge=1, le=2000)) -> dict[str, Any]:
    try:
        snapshot = jobs.get(job_id, tail=tail)
    except KeyError as exc:
        raise AppError(
            code="job_not_found",
            title="Job not found",
            message="The requested job does not exist.",
            details={"job_id": job_id},
            hints=["Refresh the jobs page and retry."],
            status_code=404,
        ) from exc
    path = str(snapshot.log_path) if snapshot.log_path is not None else None
    return {
        "job_id": job_id,
        "path": path,
        "exists": bool(snapshot.log_path and Path(snapshot.log_path).exists()),
        "tail": tail,
        "lines": list(snapshot.log_lines),
        "download_url": f"/jobs/{job_id}/logs/download" if snapshot.log_path is not None else None,
    }


@router.get("/logs/unified", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def api_logs(
    source: str = Query("webui"),
    name: str | None = None,
    tail: int = Query(100, ge=1, le=1000),
    services=Depends(get_services),
) -> dict[str, Any]:
    lifecycle = _lifecycle_service(services)
    log_file = _log_source_path(lifecycle, source=source, name=name, services=services)
    lines = _tail_file(log_file, tail=tail)
    return {
        "source": source,
        "name": name,
        "path": str(log_file),
        "exists": log_file.exists(),
        "tail": tail,
        "lines": lines,
    }




@router.get("/snapshots", response_model=SnapshotListResponse, responses={500: {"model": ErrorEnvelope}})
def list_snapshots(
    services=Depends(get_services),
    name: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    return {"items": [serialize_value(item) for item in services.snapshots().list(chroot_name=name, limit=limit)]}


@router.post("/snapshots", response_model=ApiActionResponse, responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def create_snapshot_action(
    action: ActionRequest,
    services=Depends(get_services),
):
    if action.action.strip().lower() != "create":
        raise AppError(code="unsupported_snapshot_action", title="Unsupported snapshot action", message="Only create is currently supported here.")
    target = str(action.target or "").strip()
    if not target:
        raise AppError(code="snapshot_target_required", title="Snapshot target required", message="Choose a chroot before creating a snapshot.")
    name = str(action.payload.get("name") or "snapshot").strip() or "snapshot"
    note = str(action.payload.get("note") or "").strip()
    result = services.snapshots().create(target, name=name, note=note)
    return {"status": "ok", "result": serialize_value(result)}




@router.post("/jobs/{job_id}/retry", response_model=ApiActionResponse, summary="Replay a failed job with optional overrides", responses={400: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}, openapi_extra={"requestBody": {"content": {"application/json": {"example": {"overrides": {"username": "mike", "mirror": "https://example.invalid/mirror"}}}}}})
def retry_job(job_id: str, payload: JobRetryRequest, jobs=Depends(get_jobs), services=Depends(get_services)) -> dict[str, Any]:
    try:
        snapshot = jobs.get(job_id, tail=0)
    except KeyError as exc:
        raise AppError(
            code="job_not_found",
            title="Job not found",
            message="The requested job does not exist.",
            details={"job_id": job_id},
            status_code=404,
        ) from exc
    retry = _retry_payload(snapshot)
    retry["payload"] = _merged_retry_payload(retry.get("payload") if isinstance(retry.get("payload"), dict) else {}, payload.overrides)
    queued = _submit_retry_job(jobs=jobs, services=services, retry=retry)
    return {
        "job_id": queued.job_id,
        "status": "queued",
        "location": _job_redirect_url(queued.job_id),
        "result": {"replayed_from": job_id, "retry": retry},
    }



@router.get("/registry/repair/preview-detailed", responses={500: {"model": ErrorEnvelope}})
def registry_repair_preview_detailed(services=Depends(get_services)) -> dict[str, Any]:
    return {"items": services.repair().preview_items()}



@router.post("/registry/repair/preview-selective", response_model=RegistryRepairPlanPreviewResponse, responses={500: {"model": ErrorEnvelope}})
def registry_repair_preview_selective(
    payload: RegistryRepairPlanRequest,
    services=Depends(get_services),
) -> dict[str, Any]:
    decisions = [item.model_dump() for item in payload.decisions]
    return services.repair().preview_plan(decisions)


@router.post("/registry/repair/apply-selective", response_model=ApiActionResponse, responses={500: {"model": ErrorEnvelope}})
def registry_repair_apply_selective(
    payload: RegistryRepairPlanRequest,
    jobs=Depends(get_jobs),
    services=Depends(get_services),
) -> dict[str, Any]:
    decisions = [item.model_dump() for item in payload.decisions]
    job = _submit_job_compat(
        jobs,
        kind="registry-repair",
        title="Repair chroot registry",
        target_name="registry",
        log_path=resolve_log_path(services, name="registry"),
        retry={"action": "registry.repair.apply-selective", "payload": {"decisions": decisions}, "label": "Run repair again", "href": "/repair"},
        runner=lambda progress: services.repair().apply_registry_repair_plan(decisions),
    )
    return {"job_id": job.job_id, "status": "queued", "location": _job_redirect_url(job.job_id)}


@router.get("/chroots/{name}/recovery/latest-snapshot", response_model=SnapshotRecoveryResponse, responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def latest_snapshot_recovery(name: str, services=Depends(get_services)) -> dict[str, Any]:
    snapshots = services.snapshots().list(chroot_name=name, limit=1)
    if not snapshots:
        return {"available": False, "snapshot": None}
    snapshot = snapshots[0]
    return {"available": True, "snapshot": serialize_value(snapshot)}


@router.post("/chroots/{name}/recovery/latest-snapshot", response_model=ApiActionResponse, responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def recover_latest_snapshot(name: str, jobs=Depends(get_jobs), services=Depends(get_services)) -> dict[str, Any]:
    snapshots = services.snapshots().list(chroot_name=name, limit=1)
    if not snapshots:
        raise AppError(code="snapshot_not_found", title="Snapshot not found", message="No snapshots are available for this chroot.", details={"name": name}, status_code=404)
    snapshot = snapshots[0]
    payload = {"name": name, "snapshot_name": snapshot.name}
    job = _submit_job_compat(
        jobs,
        kind="snapshot-restore",
        title=f"Restore {name}:{snapshot.name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        retry={"action": "snapshot.restore", "payload": payload, "label": "Retry restore", "href": f"/chroots/{name}"},
        runner=lambda progress: services.snapshots().restore(name, snapshot.name),
    )
    return {"job_id": job.job_id, "status": "queued", "location": _job_redirect_url(job.job_id)}
@router.get("/registry/repair/preview", response_model=RegistryRepairResponse, responses={500: {"model": ErrorEnvelope}})
def registry_repair_preview(services=Depends(get_services)) -> dict[str, Any]:
    result = services.repair().preview_registry_repair()
    return {
        "scanned_paths": result.scanned_paths,
        "missing_records": list(result.missing_records),
        "missing_paths": list(result.missing_paths),
        "mismatched_paths": list(result.mismatched_paths),
        "repaired_records": list(result.repaired_records),
        "removed_records": list(result.removed_records),
        "preview": result.preview,
        "next_steps": list(result.next_steps),
    }


@router.post("/registry/repair/apply", response_model=ApiActionResponse, responses={500: {"model": ErrorEnvelope}})
def registry_repair_apply(jobs=Depends(get_jobs), services=Depends(get_services)) -> dict[str, Any]:
    job = _submit_job_compat(
        jobs,
        kind="registry-repair",
        title="Repair chroot registry",
        target_name="registry",
        log_path=resolve_log_path(services, name="registry"),
        retry={"action": "registry.repair.apply", "payload": {}, "label": "Run repair again", "href": "/doctor/host"},
        runner=lambda progress: services.repair().apply_registry_repair(),
    )
    return {"job_id": job.job_id, "status": "queued", "location": _job_redirect_url(job.job_id)}

@router.post(
    "/transfer/upload/init",
    response_model=UploadSessionResponse,
    summary="Start a resumable transfer upload session",
    responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
)
def init_transfer_upload(
    payload: UploadInitRequest,
    services=Depends(get_services),
) -> dict[str, Any]:
    return serialize_value(
        services.transfer().start_upload(
            filename=payload.filename,
            total_size=payload.total_size,
            content_type=payload.content_type,
        )
    )


@router.get(
    "/transfer/upload/{session_id}",
    response_model=UploadSessionResponse,
    summary="Get resumable upload session status",
    responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
)
def transfer_upload_status(
    session_id: str,
    services=Depends(get_services),
) -> dict[str, Any]:
    return serialize_value(services.transfer().upload_status(session_id))


@router.put(
    "/transfer/upload/{session_id}/chunk",
    response_model=UploadSessionResponse,
    summary="Upload a resumable transfer chunk",
    responses={404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
)
async def transfer_upload_chunk(
    session_id: str,
    request: Request,
    offset: int = Query(..., ge=0, description="Byte offset expected by the server before this chunk is written."),
    services=Depends(get_services),
) -> dict[str, Any]:
    body = await request.body()
    return serialize_value(services.transfer().upload_chunk(session_id=session_id, offset=offset, data=body))


@router.post(
    "/transfer/upload/{session_id}/complete",
    response_model=UploadSessionResponse,
    summary="Finalize a resumable transfer upload",
    responses={404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
)
def transfer_upload_complete(
    session_id: str,
    payload: UploadCompleteRequest,
    services=Depends(get_services),
) -> dict[str, Any]:
    return serialize_value(services.transfer().complete_upload(session_id=session_id, expected_size=payload.expected_size))


@router.delete(
    "/transfer/upload/{session_id}",
    response_model=UploadAbortResponse,
    summary="Abort a resumable transfer upload",
    responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
)
def transfer_upload_abort(
    session_id: str,
    services=Depends(get_services),
) -> dict[str, Any]:
    return serialize_value(services.transfer().abort_upload(session_id=session_id))



@router.get("/events", response_model=EventListResponse, responses={500: {"model": ErrorEnvelope}})
def recent_events(limit: int = Query(20, ge=1, le=100), services=Depends(get_services)) -> dict[str, Any]:
    return {"items": [event.to_display_dict() for event in services.audit().recent(limit=limit)]}


@router.post("/support-bundle", response_model=SupportBundleApiResponse, responses={500: {"model": ErrorEnvelope}})
def create_support_bundle(services=Depends(get_services), jobs=Depends(get_jobs)) -> dict[str, Any]:
    result = services.support().export_bundle(None, jobs=jobs)
    return {"archive": str(result.archive), "included": list(result.included)}
def _chroot_summary(services) -> dict[str, Any]:
    rows = services.chroots().list()
    mounted = 0
    failed = 0
    details: list[dict[str, Any]] = []
    for row in rows:
        running = False
        try:
            status_rows = services.system().status(row.name)
            running = bool(status_rows) and all(getattr(item, "result", "") == "PASS" for item in status_rows)
            mounted += 1 if running else 0
        except Exception:
            failed += 1
        details.append(
            {
                "name": row.name,
                "distro": row.distro,
                "phase": row.phase,
                "installed": row.installed,
                "running": running,
            }
        )
    return {
        "installed": sum(1 for row in rows if row.installed),
        "registered": len(rows),
        "mounted": mounted,
        "running": mounted,
        "failed": failed,
        "items": details,
    }


def _run_chroot_action(services, *, action: str, target: str, progress) -> Any:
    progress(f"Running {action} for {target}")
    if action == "start":
        return services.chroots().start(target)
    if action == "restart":
        return services.chroots().restart(target)
    if action == "status":
        return services.system().status(target)
    if action == "doctor":
        return services.system().doctor(target)
    if action == "logs":
        return services.system().logs(target)
    runtime = services.runtime_for(target)
    if action == "mount":
        return runtime.controller.mount()
    if action == "unmount":
        return runtime.controller.unmount()
    raise RuntimeError(f"unsupported chroot action: {action}")


def _install_request_from_payload(payload: dict[str, Any]) -> InstallRequest:
    try:
        return InstallRequest(
            distro=str(payload["distro"]),
            name=str(payload["name"]),
            username=str(payload["username"]),
            profile=_optional_str(payload.get("profile")),
            desktop=_optional_str(payload.get("desktop")),
            release=_optional_str(payload.get("release")),
            version=_optional_str(payload.get("version")),
            tools=tuple(str(item) for item in payload.get("tools", ()) or ()),
            addons=tuple(str(item) for item in payload.get("addons", ()) or ()),
            repair=bool(payload.get("repair", False)),
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing install field: {exc.args[0]}") from exc


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _log_source_path(lifecycle, *, source: str, name: str | None, services):
    normalized = source.strip().lower()
    if normalized == "webui":
        return lifecycle.paths.webui_log_file
    if normalized == "install":
        return lifecycle.paths.install_log_file
    if normalized in {"dependencies", "dependency"}:
        return lifecycle.paths.dependency_log_file
    if normalized in {"chroot", "target"}:
        return services.config_for(name).log_file
    return lifecycle.paths.webui_log_file


def _tail_file(path, *, tail: int) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    return lines[-tail:]


class _FallbackLifecycle:
    class paths:
        from pathlib import Path
        webui_log_file = Path("/data/adb/modules/chrootctl-magisk/var/log/chrootctl-webui.log")
        install_log_file = Path("/data/adb/modules/chrootctl-magisk/config/chrootctl/python-detection.txt")
        dependency_log_file = Path("/data/adb/modules/chrootctl-magisk/config/chrootctl/dependency-bootstrap.log")

    def status(self, *, host: str = "127.0.0.1", port: int = 8420):
        return {
            "running": True,
            "state": "running",
            "url": f"http://{host}:{port}",
            "module": {"id": "chrootctl-magisk", "version": None, "installed": False},
            "python": {"dependencies_ready": True, "missing": []},
        }

    def start_webui(self):
        return {"ok": True, "action": "start", "fallback": True}

    def stop_webui(self):
        return {"ok": True, "action": "stop", "fallback": True}

    def restart_webui(self):
        return {"ok": True, "action": "restart", "fallback": True}


def _lifecycle_service(services):
    if hasattr(services, "lifecycle"):
        return services.lifecycle()
    return _FallbackLifecycle()


def _lifecycle_status(services, *, host: str, port: int):
    return _lifecycle_service(services).status(host=host, port=port)


def _transfer_temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "chrootctl-webui-transfer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _transfer_temp_payload() -> dict[str, Any]:
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
    return {"directory": str(directory), "count": len(items), "items": items}


def _delete_transfer_temp(*, path: str | None = None, delete_all: bool = False) -> dict[str, Any]:
    payload = _transfer_temp_payload()
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
    return {"removed": removed, **_transfer_temp_payload()}


def _check_summary_payload(rows: list[Any]) -> dict[str, int]:
    summary = {"pass": 0, "warn": 0, "fail": 0}
    for row in rows:
        result = str(getattr(row, "result", "")).upper()
        if result == "PASS":
            summary["pass"] += 1
        elif result == "WARN":
            summary["warn"] += 1
        else:
            summary["fail"] += 1
    return summary

@router.get(
    "/chroots/validate-import/{name}",
    tags=["chroots"],
    responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
)
def api_validate_imported_chroot(name: str, services=Depends(get_services)) -> dict[str, Any]:
    try:
        result = services.chroots().validate_imported(name)
    except RuntimeError as exc:
        raise AppError(code="chroot_not_found", title="Chroot not found", message=str(exc), status_code=404) from exc
    return {"name": name, "validation": serialize_value(result)}





def _submit_job_compat(jobs, **kwargs):
    try:
        return jobs.submit(**kwargs)
    except TypeError:
        kwargs.pop("retry", None)
        return jobs.submit(**kwargs)


def _retry_payload(job_snapshot) -> dict[str, Any]:
    payload = job_snapshot.to_event_payload(log_download_url=f"/jobs/{job_snapshot.job_id}/logs/download")
    retry = payload.get("retry")
    if isinstance(retry, dict):
        return retry
    raise AppError(
        code="job_retry_unavailable",
        title="Retry unavailable",
        message="This job does not contain enough retry metadata to replay it.",
        details={"job_id": payload.get("job_id")},
        hints=["Open the original page and submit the action again."],
        status_code=400,
    )


def _merged_retry_payload(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _job_redirect_url(job_id: str) -> str:
    return f"/jobs/{job_id}"


def _submit_retry_job(*, jobs, services, retry: dict[str, Any]):
    action = str(retry.get("action", "")).strip()
    payload = retry.get("payload") if isinstance(retry.get("payload"), dict) else {}
    log_name = str(payload.get("name") or retry.get("target") or "job")
    if action == "install.submit":
        install_payload = InstallRequest(
            distro=str(payload.get("distro", "")),
            name=str(payload.get("name", "")),
            username=str(payload.get("username", "")),
            preset=_optional_str(payload.get("preset")),
            profile=_optional_str(payload.get("profile")),
            desktop=_optional_str(payload.get("desktop")),
            release=_optional_str(payload.get("release")),
            version=_optional_str(payload.get("version")),
            mirror=_optional_str(payload.get("mirror")),
            tools=tuple(payload.get("tools", []) or []),
            addons=tuple(payload.get("addons", []) or []),
            repair=bool(payload.get("repair", False)),
        )
        return _submit_job_compat(
            jobs,
            kind="install",
            title=f"Install {install_payload.distro or 'chroot'} ({install_payload.name})",
            target_name=install_payload.name,
            log_path=resolve_log_path(services, name=install_payload.name, username=install_payload.username),
            retry={"action": action, "payload": payload, "label": "Retry install", "href": f"/install?name={install_payload.name}"},
            runner=lambda progress: services.install().install(install_payload, progress=progress),
        )
    if action == "transfer.export":
        archive = Path(str(payload.get("archive", ""))).expanduser()
        target = str(payload.get("name", ""))
        password = _optional_str(payload.get("password"))
        return _submit_job_compat(
            jobs,
            kind="transfer-export",
            title=f"Export chroot {target}",
            target_name=target,
            log_path=resolve_log_path(services, name=target),
            retry={"action": action, "payload": payload, "label": "Retry export", "href": f"/transfer?archive={archive}"},
            runner=lambda progress: services.chroots().export(target, archive=archive, password=password),
        )
    if action == "transfer.import":
        archive = Path(str(payload.get("archive", ""))).expanduser()
        return _submit_job_compat(
            jobs,
            kind="transfer-import",
            title=f"Import archive {archive.name}",
            target_name=str(payload.get("name", "")) or None,
            log_path=resolve_log_path(services, name=str(payload.get("name", "")) or None),
            retry={"action": action, "payload": payload, "label": "Retry import", "href": f"/transfer?archive={archive}"},
            runner=lambda progress: services.chroots().import_archive(
                archive,
                name=_optional_str(payload.get("name")),
                conflict=str(payload.get("conflict", "rename")),
                password=_optional_str(payload.get("password")),
                post_import=str(payload.get("post_import", "register")),
            ),
        )
    if action in {"registry.repair.apply", "registry.repair.apply-selective"}:
        decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
        return _submit_job_compat(
            jobs,
            kind="registry-repair",
            title="Repair chroot registry",
            target_name="registry",
            log_path=resolve_log_path(services, name="registry"),
            retry={"action": action, "payload": payload, "label": "Run repair again", "href": "/repair"},
            runner=lambda progress: services.repair().apply_registry_repair_plan(decisions) if decisions else services.repair().apply_registry_repair(),
        )
    if action == "chroot.start":
        name = str(payload.get("name", ""))
        return _submit_job_compat(
            jobs,
            kind="chroot-start",
            title=f"Start chroot {name}",
            target_name=name,
            log_path=resolve_log_path(services, name=name),
            retry={"action": action, "payload": payload, "label": "Retry start", "href": f"/chroots/{name}"},
            runner=lambda progress: services.chroots().start(name),
        )
    if action == "chroot.restart":
        name = str(payload.get("name", ""))
        return _submit_job_compat(
            jobs,
            kind="chroot-restart",
            title=f"Restart chroot {name}",
            target_name=name,
            log_path=resolve_log_path(services, name=name),
            retry={"action": action, "payload": payload, "label": "Retry restart", "href": f"/chroots/{name}"},
            runner=lambda progress: services.chroots().restart(name),
        )
    if action == "chroot.upgrade":
        name = str(payload.get("name", ""))
        return _submit_job_compat(
            jobs,
            kind="chroot-upgrade",
            title=f"Upgrade chroot {name}",
            target_name=name,
            log_path=resolve_log_path(services, name=name),
            retry={"action": action, "payload": payload, "label": "Retry upgrade", "href": f"/chroots/{name}"},
            runner=lambda progress: services.install().upgrade(name, progress=progress),
        )
    if action == "snapshot.create":
        name = str(payload.get("name", ""))
        snapshot_name = str(payload.get("snapshot_name", "snapshot"))
        note = str(payload.get("note", ""))
        return _submit_job_compat(
            jobs,
            kind="snapshot-create",
            title=f"Snapshot {name}:{snapshot_name}",
            target_name=name,
            log_path=resolve_log_path(services, name=name),
            retry={"action": action, "payload": payload, "label": "Retry snapshot", "href": f"/chroots/{name}"},
            runner=lambda progress: services.snapshots().create(name, name=snapshot_name, note=note),
        )
    if action == "snapshot.restore":
        name = str(payload.get("name", ""))
        snapshot_name = str(payload.get("snapshot_name", ""))
        return _submit_job_compat(
            jobs,
            kind="snapshot-restore",
            title=f"Restore {name}:{snapshot_name}",
            target_name=name,
            log_path=resolve_log_path(services, name=name),
            retry={"action": action, "payload": payload, "label": "Retry restore", "href": f"/chroots/{name}"},
            runner=lambda progress: services.snapshots().restore(name, snapshot_name),
        )
    if action == "snapshot.export":
        name = str(payload.get("name", ""))
        snapshot_name = str(payload.get("snapshot_name", ""))
        return _submit_job_compat(
            jobs,
            kind="snapshot-export",
            title=f"Export snapshot {name}:{snapshot_name}",
            target_name=name,
            log_path=resolve_log_path(services, name=name),
            retry={"action": action, "payload": payload, "label": "Retry export", "href": f"/chroots/{name}"},
            runner=lambda progress: services.snapshots().export(name, snapshot_name),
        )
    raise AppError(
        code="job_retry_action_unknown",
        title="Retry action unavailable",
        message=f"Unsupported retry action: {action or 'unknown'}",
        details={"retry": retry},
        hints=["Open the original page and submit the action again."],
        status_code=400,
    )

