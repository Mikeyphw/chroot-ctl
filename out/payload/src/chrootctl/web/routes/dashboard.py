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
            "cross_arch_state": _safe_cross_arch_state(services),
            "host_doctor_rows": _safe_host_doctor_rows(services),
            "foreign_arch_advisories": _safe_foreign_arch_advisories(services),
            "page_title": "Dashboard",
            "recent_builds": _recent_builds(jobs),
            "recent_events": services.audit().recent(limit=8),
            "quickstart": _safe_quickstart(services),
        },
    )


def _lifecycle_status(request: Request, services):
    if hasattr(services, "lifecycle"):
        try:
            return services.lifecycle().status(
                host=request.app.state.web_security.bind_host,
                port=request.app.state.web_security.bind_port,
            )
        except Exception:
            pass
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

def _safe_cross_arch_state(services):
    try:
        return services.system().cross_arch_state()
    except Exception:
        return {"host_arch": "unknown", "targets": []}

def _safe_host_doctor_rows(services):
    try:
        return services.system().host_doctor()
    except Exception:
        return []

def _safe_foreign_arch_advisories(services):
    try:
        return services.system().foreign_arch_advisories()
    except Exception:
        return []


def _recent_builds(jobs):
    try:
        return [job for job in jobs.list_recent(limit=6, tail=4) if getattr(job, "kind", "") == "build"]
    except Exception:
        return []


def _safe_quickstart(services):
    try:
        return services.system().quickstart()
    except Exception:
        return {
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
