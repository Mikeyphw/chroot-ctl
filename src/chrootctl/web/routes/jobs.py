from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..deps import get_jobs, get_templates

router = APIRouter(prefix="/jobs", tags=["jobs"])




@router.get("/{job_id}")
def show_job(job_id: str, request: Request, jobs=Depends(get_jobs), templates=Depends(get_templates)):
    try:
        job = jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "page_title": f"Job · {job.title}",
            "job": job,
        },
    )


@router.get("/{job_id}/events")
async def stream_job(job_id: str, jobs=Depends(get_jobs)):
    async def event_stream():
        while True:
            try:
                payload = jobs.event_payload(job_id)
            except KeyError:
                yield "event: error\ndata: " + json.dumps({"error": "job not found"}) + "\n\n"
                return
            yield "data: " + json.dumps(payload) + "\n\n"
            if payload["complete"]:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
