from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from ...magisk import MagiskModuleConfig, render_magisk_module, resolve_startup_targets, validate_magisk_module, zip_magisk_module
from ...models import AppBuildResult
from ..deps import get_jobs, get_services, get_templates

router = APIRouter(prefix="/build", tags=["build"])


def _artifact_root() -> Path:
    root = Path(tempfile.gettempdir()) / "chrootctl-web-builds"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _job_payload(job, job_id: str) -> dict[str, object]:
    payload = job.to_event_payload(log_download_url=f"/jobs/{job_id}/logs/download")
    result = getattr(job, "result_payload", None)
    artifact_path = getattr(result, "artifact_path", None)
    if artifact_path is not None:
        payload["artifact_download_url"] = f"/build/artifacts/{job_id}"
    return payload


def _recent_builds(jobs) -> list[dict[str, object]]:
    return [_job_payload(job, job.job_id) for job in jobs.list_recent(limit=10, tail=8) if job.kind == "build"]


@router.get("")
def show_build_page(
    request: Request,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
    templates=Depends(get_templates),
):
    installed = tuple(chroot.name for chroot in services.chroots().list() if chroot.installed)
    return templates.TemplateResponse(
        request,
        "build_module.html",
        {
            "page_title": "Build module",
            "installed_chroots": installed,
            "recent_builds": _recent_builds(jobs),
        },
    )


@router.post("/module")
def queue_module_build(
    jobs=Depends(get_jobs),
    services=Depends(get_services),
    include_all_installed: bool = Form(False),
    selected_names: str = Form(""),
    wheelhouse: str = Form(""),
):
    selected = tuple(name.strip() for name in selected_names.split(",") if name.strip())
    wheelhouse_dir = Path(wheelhouse).expanduser() if wheelhouse.strip() else None
    artifact_root = _artifact_root()

    def runner(progress):
        progress({"phase": "resolve", "message": "Resolving startup targets", "percent": 10})
        startup_targets = resolve_startup_targets(
            services,
            selected_names=selected,
            all_installed=bool(include_all_installed),
        )
        build_dir = Path(tempfile.mkdtemp(prefix="chrootctl-build-", dir=str(artifact_root)))
        progress({"phase": "render", "message": "Rendering module payload", "percent": 35})
        result = render_magisk_module(
            build_dir / "module",
            services=services,
            startup_targets=startup_targets,
            module_config=MagiskModuleConfig(offline_wheelhouse_dir=wheelhouse_dir),
        )
        progress({"phase": "validate", "message": "Validating module layout", "percent": 70})
        validate_magisk_module(result.output_dir)
        zip_path = build_dir / "chrootctl-magisk-webui.zip"
        progress({"phase": "zip", "message": "Creating flashable zip", "percent": 90})
        zip_magisk_module(result.output_dir, zip_path)
        return AppBuildResult(
            artifact_name=zip_path.name,
            artifact_path=zip_path,
            output_dir=result.output_dir,
            startup_targets=startup_targets,
        )

    snapshot = jobs.submit(kind="build", title="Build Magisk module", runner=runner)
    services.audit().record("build.module", target="magisk", message="Magisk module build queued")
    return RedirectResponse(url=f"/jobs/{snapshot.job_id}?toast=Build queued&toast_kind=ok", status_code=303)


@router.get("/artifacts/{job_id}")
def download_build_artifact(job_id: str, jobs=Depends(get_jobs)):
    try:
        job = jobs.get(job_id, tail=0)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    result = job.result_payload
    artifact_path = getattr(result, "artifact_path", None)
    artifact_name = getattr(result, "artifact_name", None)
    if artifact_path is None:
        raise HTTPException(status_code=404, detail="artifact not available")
    path = Path(artifact_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path=path, filename=artifact_name or path.name, media_type="application/zip")
