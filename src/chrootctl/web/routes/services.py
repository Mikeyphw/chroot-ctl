from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...runtime.units import ServiceRunner
from ..deps import get_services, get_templates
from ..serialize import serialize_value

router = APIRouter(prefix="/services", tags=["services"])


def _runner(services: Any) -> ServiceRunner:
    return ServiceRunner.from_services(services)


@router.get("")
def services_page(request: Request, services=Depends(get_services), templates=Depends(get_templates)):
    runner = _runner(services)
    rows = runner.list()
    return templates.TemplateResponse(
        request,
        "services.html",
        {
            "page_title": "Services",
            "services": rows,
            "service_dirs": services.base_config.service_dirs,
            "service_state_dir": services.base_config.service_state_dir,
            "service_log_dir": services.base_config.service_log_dir,
        },
    )


@router.get("/api/list")
def api_services(services=Depends(get_services)):
    return {"items": _runner(services).list()}


@router.get("/api/{service_name}")
def api_service(service_name: str, chroot: str | None = None, tail: int = 120, services=Depends(get_services)):
    runner = _runner(services)
    return {
        "status": serialize_value(runner.status(service_name, chroot=chroot)),
        "journal": serialize_value(runner.logs(service_name, chroot=chroot, tail=None if tail == 0 else tail)),
    }


@router.get("/{service_name}")
def service_detail(
    service_name: str,
    request: Request,
    chroot: str | None = None,
    tail: int = 120,
    services=Depends(get_services),
    templates=Depends(get_templates),
):
    runner = _runner(services)
    try:
        status = runner.status(service_name, chroot=chroot)
        journal = runner.logs(service_name, chroot=chroot, tail=None if tail == 0 else tail)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request,
        "service_detail.html",
        {
            "page_title": f"Service · {service_name}",
            "status": status,
            "journal": journal,
            "tail": tail,
            "lines": str(journal.get("text", "")).splitlines(),
        },
    )


@router.post("/{service_name}/start")
def start_service(service_name: str, chroot: str | None = Form(None), services=Depends(get_services)):
    _runner(services).start(service_name, chroot=chroot or None)
    return _redirect(service_name, chroot=chroot, toast="Service started")


@router.post("/{service_name}/stop")
def stop_service(service_name: str, chroot: str | None = Form(None), services=Depends(get_services)):
    _runner(services).stop(service_name, chroot=chroot or None)
    return _redirect(service_name, chroot=chroot, toast="Service stopped")


@router.post("/{service_name}/restart")
def restart_service(service_name: str, chroot: str | None = Form(None), services=Depends(get_services)):
    _runner(services).restart(service_name, chroot=chroot or None)
    return _redirect(service_name, chroot=chroot, toast="Service restarted")


@router.post("/{service_name}/enable")
def enable_service(service_name: str, chroot: str | None = Form(None), target: str = Form("boot.target"), services=Depends(get_services)):
    _runner(services).enable(service_name, chroot=chroot or None, target=target)
    return _redirect(service_name, chroot=chroot, toast="Service enabled")


@router.post("/{service_name}/disable")
def disable_service(service_name: str, chroot: str | None = Form(None), target: str = Form("boot.target"), services=Depends(get_services)):
    _runner(services).disable(service_name, chroot=chroot or None, target=target)
    return _redirect(service_name, chroot=chroot, toast="Service disabled")



def _redirect(service_name: str, *, chroot: str | None, toast: str) -> RedirectResponse:
    suffix = f"?chroot={chroot}" if chroot else ""
    glue = "&" if suffix else "?"
    return RedirectResponse(f"/services/{service_name}{suffix}{glue}toast={toast}", status_code=303)
