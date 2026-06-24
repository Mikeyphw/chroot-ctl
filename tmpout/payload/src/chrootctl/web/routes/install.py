from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..deps import get_jobs, get_services, get_templates, resolve_log_path
from ...models import InstallRequest

router = APIRouter(prefix="/install", tags=["install"])


def _install_request_from_values(
    *,
    distro: str,
    name: str,
    username: str,
    profile: str | None,
    desktop: str | None,
    release: str | None,
    version: str | None,
    tools: list[str] | tuple[str, ...] = (),
    addons: list[str] | tuple[str, ...] = (),
    repair: bool = False,
) -> InstallRequest:
    return InstallRequest(
        distro=distro.strip(),
        name=name.strip(),
        username=(username or "").strip(),
        profile=(profile or "").strip() or None,
        desktop=(desktop or "").strip() or None,
        release=(release or "").strip() or None,
        version=(version or "").strip() or None,
        tools=tuple(tools),
        addons=tuple(addons),
        repair=repair,
    )


@router.get("")
def install_wizard(
    request: Request,
    services=Depends(get_services),
    templates=Depends(get_templates),
    distro: str | None = None,
    name: str | None = None,
):
    install_service = services.install()
    try:
        form_state = install_service.install_form_state(name=name, distro=distro)
    except Exception:
        form_state = {
            "defaults": {"distro": distro, "name": name, "username": None, "profile": "minimal", "desktop": "none", "release": None, "version": None},
            "distros": [{"id": item, "label": item.title()} for item in install_service.distros()],
            "profiles": _profile_options(install_service),
            "desktops": _desktop_options(install_service),
            "users": [],
            "requirements": {"username_required": True, "root_required": True},
            "rules": {"minimal_forces_desktop": "none", "minimal_rejects_desktop": True},
        }
    defaults = install_service.wizard_defaults(name=name, distro=distro)
    try:
        versions = install_service.list_versions(distro=distro, name=name, username=defaults.username) if distro else []
    except Exception:
        versions = []
    return templates.TemplateResponse(
        request,
        "install_wizard.html",
        {
            "page_title": "Install Wizard",
            "defaults": defaults,
            "distros": install_service.distros(),
            "profiles": install_service.profiles(),
            "desktops": install_service.desktops(),
            "profile_options": _profile_options(install_service),
            "desktop_options": _desktop_options(install_service),
            "versions": versions,
            "tools": services.catalog("tool").list_entries(distro=distro),
            "addons": services.catalog("addon").list_entries(distro=distro),
            "form_state": form_state,
            "target_users": form_state["users"],
            "requirements": form_state["requirements"],
        },
    )


@router.get("/preview")
def install_preview(
    services=Depends(get_services),
    distro: str = "ubuntu",
    name: str = "ubuntu",
    username: str = "",
    profile: str | None = None,
    desktop: str | None = None,
    release: str | None = None,
    version: str | None = None,
    tools: list[str] = [],
    addons: list[str] = [],
):
    install_request = _install_request_from_values(
        distro=distro,
        name=name,
        username=username,
        profile=profile,
        desktop=desktop,
        release=release,
        version=version,
        tools=tools,
        addons=addons,
    )
    result = services.install().validate_install_submission(install_request)
    status = 200 if result["ok"] else 400
    return JSONResponse(result, status_code=status)


@router.post("")
def submit_install(
    request: Request,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
    distro: str = Form(...),
    name: str = Form(...),
    username: str = Form(""),
    profile: str | None = Form(None),
    desktop: str | None = Form(None),
    release: str | None = Form(None),
    version: str | None = Form(None),
    tools: list[str] = Form(default=[]),
    addons: list[str] = Form(default=[]),
    repair: str | None = Form(None),
    confirm_repair: str | None = Form(None),
):
    repair_enabled = repair is not None and repair.strip().lower() not in {"0", "false", "off", "no", ""}
    repair_confirmed = confirm_repair is not None and confirm_repair.strip().lower() not in {"0", "false", "off", "no", ""}
    if repair_enabled and not repair_confirmed:
        raise HTTPException(status_code=400, detail="confirm the repair flow before continuing")
    install_request = _install_request_from_values(
        distro=distro,
        name=name,
        username=username,
        profile=profile,
        desktop=desktop,
        release=release,
        version=version,
        tools=tools,
        addons=addons,
        repair=repair_enabled,
    )
    validation = services.install().validate_install_submission(install_request)
    if not validation["ok"]:
        detail = validation["blocking"][0]["message"] if validation["blocking"] else "install request is not valid"
        raise HTTPException(status_code=400, detail=detail)
    job = jobs.submit(
        kind="install",
        title=f"Install {install_request.name}",
        target_name=install_request.name,
        log_path=resolve_log_path(services, name=install_request.name, username=install_request.username),
        runner=lambda progress: services.install().install(install_request, progress=progress),
    )
    return RedirectResponse(url=f"/jobs/{job.job_id}?toast=Install+job+queued&toast_kind=ok", status_code=303)


def _profile_options(install_service):
    if hasattr(install_service, "profile_options"):
        return install_service.profile_options()
    return [
        {
            "id": profile,
            "label": str(profile),
            "desktop_allowed": profile not in {"minimal", "dev"},
            "default_desktop": "none" if profile in {"minimal", "dev", "custom"} else profile,
            "description": "",
        }
        for profile in install_service.profiles()
    ]


def _desktop_options(install_service):
    if hasattr(install_service, "desktop_options"):
        return install_service.desktop_options()
    return [
        {
            "id": desktop,
            "label": str(desktop),
            "lightweight": desktop in {"xfce4", "plasma"},
            "packages": (),
        }
        for desktop in install_service.desktops()
    ]
