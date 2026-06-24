from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...models import DashboardChrootCard
from ..deps import get_jobs, get_services, get_templates

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
    templates=Depends(get_templates),
):
    try:
        summary = services.system().dashboard()
    except Exception:
        summary = None
    cards: list[DashboardChrootCard] = []
    for chroot in services.chroots().list():
        try:
            users_count = len(services.users(name=chroot.name).list())
        except Exception:
            users_count = 0
        try:
            status_rows = services.system().status(chroot.name)
            running = bool(status_rows) and all(getattr(row, "result", "") == "PASS" for row in status_rows)
        except Exception:
            running = False
        try:
            doctor_rows = services.system().doctor(chroot.name)
            doctor_warnings = sum(1 for row in doctor_rows if getattr(row, "result", "") == "WARN")
            doctor_failures = sum(1 for row in doctor_rows if getattr(row, "result", "") == "FAIL")
        except Exception:
            doctor_warnings = 0
            doctor_failures = 0
        cards.append(
            DashboardChrootCard(
                name=chroot.name,
                distro=chroot.distro,
                phase=chroot.phase,
                installed=chroot.installed,
                running=running,
                user_count=users_count,
                doctor_warnings=doctor_warnings,
                doctor_failures=doctor_failures,
            )
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "summary": summary,
            "cards": cards,
            "recent_jobs": jobs.list_recent(),
            "system_state": _lifecycle_status(request, services),
            "install_state": _safe_install_state(services),
            "page_title": "Dashboard",
        },
    )


def _lifecycle_status(request: Request, services):
    if hasattr(services, "lifecycle"):
        return services.lifecycle().status(
            host=request.app.state.web_security.bind_host,
            port=request.app.state.web_security.bind_port,
        )
    return {
        "state": "running",
        "enabled": False,
        "python": {"dependencies_ready": True},
        "module": {"version": None},
    }


def _safe_install_state(services):
    try:
        return services.install().install_form_state()
    except Exception:
        return {
            "defaults": {"distro": None, "name": None, "username": None, "profile": "minimal", "desktop": "none", "release": None, "version": None},
            "distros": [],
            "profiles": [],
            "desktops": [],
            "users": [],
            "requirements": {"username_required": True, "root_required": True},
            "rules": {},
        }
