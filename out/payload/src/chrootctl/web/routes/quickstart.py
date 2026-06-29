from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..deps import get_services, get_templates

router = APIRouter(tags=["quickstart"])


@router.get("/quickstart")
def quickstart(
    request: Request,
    services=Depends(get_services),
    templates=Depends(get_templates),
):
    try:
        guide = services.system().quickstart()
    except Exception:
        guide = {
            "host_rows": [],
            "blockers": [],
            "warnings": [],
            "chroot_count": 0,
            "recommended_name": "ubuntu",
            "defaults": {"distro": "ubuntu", "preset": "minimal-server", "release": "noble", "name": "ubuntu"},
            "target_user": "",
            "can_install": False,
            "shell_target": None,
            "shell_command": "",
            "install_command": "sudo chrootctl install ubuntu --name ubuntu --preset minimal-server --release noble",
            "use_steps": [
                "Open Install and review the guided plan.",
                "Pick or create a target user, then start the install job.",
                "Open the created chroot and copy the shell command.",
            ],
        }
    return templates.TemplateResponse(
        request,
        "quickstart.html",
        {
            "page_title": "Quick Start",
            "guide": guide,
        },
    )
