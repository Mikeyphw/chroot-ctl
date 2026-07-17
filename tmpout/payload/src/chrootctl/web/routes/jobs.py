from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..deps import get_jobs, get_services, get_templates

router = APIRouter(prefix="/jobs", tags=["jobs"])




def _job_payload(job, job_id: str) -> dict[str, object]:
    payload = job.to_event_payload(log_download_url=f"/jobs/{job_id}/logs/download")
    result = payload.get("result_payload") or {}
    if isinstance(result, dict) and result.get("artifact_path"):
        payload["artifact_download_url"] = f"/build/artifacts/{job_id}"
    return payload


@router.get("")
def list_jobs(request: Request, jobs=Depends(get_jobs), templates=Depends(get_templates)):
    items = [_job_payload(job, job.job_id) for job in jobs.list_recent(limit=20, tail=8)]
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "page_title": "Jobs",
            "jobs": items,
        },
    )


@router.get("/{job_id}")
def show_job(job_id: str, request: Request, jobs=Depends(get_jobs), services=Depends(get_services), templates=Depends(get_templates)):
    try:
        job = jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "page_title": f"Job · {job.title}",
            "job": _job_payload(job, job_id),
            "recovery_snapshot": _latest_recovery_snapshot(services, job.target_name),
        },
    )


@router.get("/{job_id}/events")
async def stream_job(job_id: str, jobs=Depends(get_jobs)):
    async def event_stream():
        while True:
            try:
                payload = _job_payload(jobs.get(job_id), job_id)
            except KeyError:
                yield "event: error\ndata: " + json.dumps({"error": "job not found"}) + "\n\n"
                return
            yield "data: " + json.dumps(payload) + "\n\n"
            if payload["complete"]:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{job_id}/logs/download")
def download_job_log(job_id: str, jobs=Depends(get_jobs)):
    try:
        job = jobs.get(job_id, tail=0)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    if job.log_path is None:
        raise HTTPException(status_code=404, detail="job log not found")
    return FileResponse(path=job.log_path, media_type="text/plain; charset=utf-8", filename=job.log_path.name)


def _latest_recovery_snapshot(services, target_name: str | None):
    if not target_name:
        return None
    try:
        snapshots = services.snapshots().list(chroot_name=target_name, limit=1)
    except Exception:
        return None
    if not snapshots:
        return None
    item = snapshots[0]
    return {"name": item.name, "chroot_name": item.chroot_name, "created_at": item.created_at}
