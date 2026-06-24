from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse

from ..deps import get_jobs, get_services, get_templates, resolve_log_path

router = APIRouter(prefix="/support", tags=["docs"])


@router.get("")
def support_page(request: Request, services=Depends(get_services), jobs=Depends(get_jobs), templates=Depends(get_templates)):
    return templates.TemplateResponse(
        request,
        "support.html",
        {
            "page_title": "Support",
            "events": services.audit().recent(limit=20),
            "recent_jobs": jobs.list_recent(limit=12, tail=5),
        },
    )


@router.post("/bundle")
def bundle_export(archive: str = Form(""), services=Depends(get_services), jobs=Depends(get_jobs)):
    target = Path(archive).expanduser() if archive.strip() else None
    result = services.support().export_bundle(target, jobs=jobs)
    return RedirectResponse(url=f"/support/download?path={result.archive}", status_code=303)


@router.get("/download")
def bundle_download(path: str, services=Depends(get_services)):
    bundle = Path(path).expanduser().resolve()
    services.audit().record("support-bundle.download", target=str(bundle), message="Support bundle downloaded")
    return FileResponse(path=bundle, media_type="application/gzip", filename=bundle.name)
