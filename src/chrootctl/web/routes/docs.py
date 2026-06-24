from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..deps import get_templates

router = APIRouter(tags=["docs"])


@router.get("/docs", include_in_schema=False)
def api_docs_page(request: Request, templates=Depends(get_templates)):
    examples = [
        {
            "title": "Validate an install request",
            "method": "POST",
            "path": "/api/install/validate",
            "body": '{\n  "distro": "ubuntu",\n  "name": "work",\n  "username": "alice",\n  "profile": "minimal",\n  "desktop": "none"\n}',
        },
        {
            "title": "Inspect a transfer archive",
            "method": "GET",
            "path": "/api/transfer/inspect?archive=/data/local/tmp/work.tar.zst",
            "body": None,
        },
        {
            "title": "Check transfer readiness",
            "method": "GET",
            "path": "/api/transfer/readiness",
            "body": None,
        },
        {
            "title": "Check a queued job",
            "method": "GET",
            "path": "/api/jobs/1?tail=50",
            "body": None,
        },
    ]
    return templates.TemplateResponse(
        request,
        "api_docs.html",
        {
            "page_title": "API docs",
            "openapi_url": request.app.openapi_url,
            "swagger_url": request.app.docs_url,
            "examples": examples,
            "error_example": {
                "error": {
                    "code": "missing_username",
                    "title": "Missing target user",
                    "message": "Choose or create a non-root user before starting the install.",
                    "details": {"field": "username"},
                    "hints": ["Create a user inline or pass --username."],
                    "actions": [{"label": "Open install wizard", "href": "/install"}],
                    "retryable": True,
                }
            },
        },
    )
