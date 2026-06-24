from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..deps import get_templates

router = APIRouter(prefix="/faq", tags=["docs"])


@router.get("")
def faq_page(request: Request, templates=Depends(get_templates)):
    items = (
        {
            "question": "Why does foreign-arch install stop after extract?",
            "answer": "The host can create the rootfs, but bootstrap/finalize need matching architecture or qemu/binfmt support. Export the tar.zst and import it on the phone to finish there.",
        },
        {
            "question": "How do encrypted transfer archives work?",
            "answer": "Exports can be wrapped with openssl. Import and inspect require the same password used during export.",
        },
        {
            "question": "What should I include in a support bundle?",
            "answer": "The built-in support bundle includes sanitized config, recent jobs, recent audit events, host doctor output, and current logs.",
        },
    )
    return templates.TemplateResponse(request, "faq.html", {"page_title": "FAQ", "faq_items": items})
