from __future__ import annotations

from typing import Any
from pathlib import Path
import tempfile

from fastapi import APIRouter, Depends, Query, Request
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




@router.post("/install/preview", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
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


@router.get("/transfer/preview/export", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def preview_export(name: str = Query(..., min_length=1), archive: str | None = None, services=Depends(get_services)) -> dict[str, Any]:
    return services.chroots().export_preview(name.strip(), archive=Path(archive).expanduser() if archive else None)


@router.get("/transfer/preview/import", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def preview_import(archive: str = Query(..., min_length=1), name: str | None = None, conflict: str = Query("rename"), services=Depends(get_services)) -> dict[str, Any]:
    return services.chroots().import_preview(Path(archive).expanduser(), name=name, conflict=conflict)


@router.get("/transfer/preview/delete", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def preview_delete(name: str = Query(..., min_length=1), services=Depends(get_services)) -> dict[str, Any]:
    return services.chroots().delete_preview(name.strip())


@router.get("/transfer/temp", responses={500: {"model": ErrorEnvelope}})
def transfer_temp_state() -> dict[str, Any]:
    return _transfer_temp_payload()


@router.delete("/transfer/temp", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def delete_transfer_temp(path: str | None = None, delete_all: bool = False) -> dict[str, Any]:
    return _delete_transfer_temp(path=path, delete_all=delete_all)


@router.get("/transfer/inspect", responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}})
def inspect_transfer_archive(archive: str, services=Depends(get_services)) -> dict[str, Any]:
    chroots = services.chroots()
    if hasattr(chroots, "inspect_archive"):
        inspection = chroots.inspect_archive(Path(archive))
    else:
        inspection = {"archive": str(Path(archive).expanduser().resolve()), "source_name": Path(archive).name.removesuffix(".tar.zst").replace(".tar", ""), "suggested_name": Path(archive).name.removesuffix(".tar.zst").replace(".tar", ""), "path_name": Path(archive).name.removesuffix(".tar.zst").replace(".tar", ""), "distro": "unknown", "arch": "unknown", "release_name": "", "version": "", "phase": "extract", "installed": False, "metadata": {}}
    return serialize_value(inspection)


@router.get("/transfer/readiness", response_model=TransferReadinessResponse, responses={500: {"model": ErrorEnvelope}})
def transfer_readiness(services=Depends(get_services)) -> dict[str, Any]:
    return services.system().cross_arch_state()



@router.get("/doctor/host", response_model=DoctorReadinessResponse, responses={500: {"model": ErrorEnvelope}})
def doctor_host(services=Depends(get_services)) -> dict[str, Any]:
    rows = services.system().host_doctor()
    advisories = services.system().foreign_arch_advisories()
    blockers = [serialize_value(row) for row in rows if getattr(row, "result", "") == "FAIL"]
    blockers.extend(item for item in advisories if item.get("mode") != "ready")
    return {
        "host_arch": services.runtime_for().runner.host_arch(),
        "checks": [serialize_value(row) for row in rows],
        "summary": _check_summary_payload(rows),
        "advisories": advisories,
        "blockers": blockers,
    }




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


