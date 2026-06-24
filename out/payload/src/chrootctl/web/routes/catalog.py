from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..deps import get_jobs, get_services, get_templates, resolve_log_path

router = APIRouter(tags=["catalog"])


def _job_redirect(job_id: str, *, toast: str = "Job queued") -> RedirectResponse:
    return RedirectResponse(url=f"/jobs/{job_id}?toast={toast.replace(' ', '+')}&toast_kind=ok", status_code=303)


def _catalog_slug(kind: str) -> str:
    return "tools" if kind == "tool" else "addons"


def _filter_entries(entries, *, query: str | None):
    if not query:
        return list(entries)
    needle = query.strip().lower()
    if not needle:
        return list(entries)
    return [
        entry
        for entry in entries
        if needle in entry.name.lower()
        or needle in entry.description.lower()
        or any(needle in category.lower() for category in entry.categories)
        or any(needle in distro.lower() for distro in entry.distros)
    ]


def _catalog_page(
    kind: str,
    request: Request,
    services,
    templates,
    *,
    distro: str | None = None,
    category: str | None = None,
    query: str | None = None,
    selected: str | None = None,
):
    service = services.catalog(kind)
    entries = _filter_entries(service.list_entries(distro=distro, category=category), query=query)
    selected_entry = None
    if selected:
        try:
            selected_entry = service.get_entry(selected)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown {kind}: {selected}") from exc
    elif entries:
        selected_entry = entries[0]
    return templates.TemplateResponse(
        request,
        "catalog.html",
        {
            "page_title": "Tools" if kind == "tool" else "Addons",
            "kind": kind,
            "kind_slug": _catalog_slug(kind),
            "entries": entries,
            "categories": service.categories(distro=distro),
            "selected_category": category,
            "selected_distro": distro,
            "query": query or "",
            "selected_entry": selected_entry,
            "distros": services.install().distros(),
            "chroots": services.chroots().list(),
        },
    )


@router.get("/tools")
def tools(
    request: Request,
    services=Depends(get_services),
    templates=Depends(get_templates),
    distro: str | None = None,
    category: str | None = None,
    q: str | None = None,
    selected: str | None = None,
):
    return _catalog_page("tool", request, services, templates, distro=distro, category=category, query=q, selected=selected)


@router.get("/addons")
def addons(
    request: Request,
    services=Depends(get_services),
    templates=Depends(get_templates),
    distro: str | None = None,
    category: str | None = None,
    q: str | None = None,
    selected: str | None = None,
):
    return _catalog_page("addon", request, services, templates, distro=distro, category=category, query=q, selected=selected)


@router.get("/tools/{entry_name}")
def show_tool(entry_name: str, request: Request, services=Depends(get_services), templates=Depends(get_templates)):
    return _catalog_detail("tool", entry_name, request, services, templates)


@router.get("/addons/{entry_name}")
def show_addon(entry_name: str, request: Request, services=Depends(get_services), templates=Depends(get_templates)):
    return _catalog_detail("addon", entry_name, request, services, templates)


def _catalog_detail(kind: str, entry_name: str, request: Request, services, templates):
    service = services.catalog(kind)
    try:
        entry = service.get_entry(entry_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown {kind}: {entry_name}") from exc
    return templates.TemplateResponse(
        request,
        "catalog_detail.html",
        {
            "page_title": f"{'Tool' if kind == 'tool' else 'Addon'} · {entry.name}",
            "kind": kind,
            "kind_slug": _catalog_slug(kind),
            "entry": entry,
            "chroots": services.chroots().list(),
        },
    )


@router.post("/tools/apply")
def apply_tools(
    name: str = Form(...),
    entries: list[str] = Form(default=[]),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    return _apply_catalog(kind="tool", name=name, entries=entries, services=services, jobs=jobs)


@router.post("/addons/apply")
def apply_addons(
    name: str = Form(...),
    entries: list[str] = Form(default=[]),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    return _apply_catalog(kind="addon", name=name, entries=entries, services=services, jobs=jobs)


def _apply_catalog(*, kind: str, name: str, entries: list[str], services, jobs):
    if not entries:
        raise HTTPException(status_code=400, detail=f"choose at least one {kind} to apply")
    job = jobs.submit(
        kind=f"{kind}-apply",
        title=f"Apply {kind}s to {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name),
        runner=lambda progress: services.catalog(kind, name=name).apply(entries, progress=progress),
    )
    return _job_redirect(job.job_id, toast="Catalog apply queued")
