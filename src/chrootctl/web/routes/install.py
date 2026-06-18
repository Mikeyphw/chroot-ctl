from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..deps import get_jobs, get_services, get_templates, resolve_log_path
from ...models import InstallRequest

router = APIRouter(prefix="/install", tags=["install"])


@router.get("")
def install_wizard(
    request: Request,
    services=Depends(get_services),
    templates=Depends(get_templates),
    distro: str | None = None,
    name: str | None = None,
):
    install_service = services.install()
    defaults = install_service.wizard_defaults(name=name, distro=distro)
    versions = install_service.list_versions(distro=distro, name=name, username=defaults.username) if distro else []
    return templates.TemplateResponse(
        request,
        "install_wizard.html",
        {
            "page_title": "Install Wizard",
            "defaults": defaults,
            "distros": install_service.distros(),
            "profiles": install_service.profiles(),
            "desktops": install_service.desktops(),
            "versions": versions,
            "tools": services.catalog("tool").list_entries(distro=distro),
            "addons": services.catalog("addon").list_entries(distro=distro),
        },
    )


@router.post("")
def submit_install(
    request: Request,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
    distro: str = Form(...),
    name: str = Form(...),
    username: str = Form(...),
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
    install_request = InstallRequest(
        distro=distro,
        name=name,
        username=username,
        profile=profile or None,
        desktop=desktop or None,
        release=release or None,
        version=version or None,
        tools=tuple(tools),
        addons=tuple(addons),
        repair=repair_enabled,
    )
    job = jobs.submit(
        kind="install",
        title=f"Install {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name, username=username),
        runner=lambda progress: services.install().install(install_request, progress=progress),
    )
    return RedirectResponse(url=f"/jobs/{job.job_id}?toast=Install+job+queued&toast_kind=ok", status_code=303)
