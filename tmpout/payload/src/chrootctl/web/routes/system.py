from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...models import CheckRow, LogLink, LogSnapshot
from ..deps import get_jobs, get_services, get_templates
from ..serialize import serialize_value

router = APIRouter(tags=["system"])


@router.get("/status")
def status(
    request: Request,
    name: str | None = None,
    details: bool = False,
    services=Depends(get_services),
    templates=Depends(get_templates),
):
    resolved_name = _resolve_target_name(services, name=name)
    rows = _check_rows_payload(services.system().status(resolved_name, details=details), name=resolved_name)
    return templates.TemplateResponse(
        request,
        "checks.html",
        {
            "page_title": f"Status · {resolved_name}",
            "title": "Status",
            "rows": rows,
            "target_name": resolved_name,
            "summary": _check_summary(rows),
        },
    )


@router.get("/doctor")
def doctor(
    request: Request,
    name: str | None = None,
    services=Depends(get_services),
    templates=Depends(get_templates),
):
    resolved_name = _resolve_target_name(services, name=name)
    rows = _check_rows_payload(services.system().doctor(resolved_name), name=resolved_name)
    return templates.TemplateResponse(
        request,
        "checks.html",
        {
            "page_title": f"Doctor · {resolved_name}",
            "title": "Doctor",
            "rows": rows,
            "target_name": resolved_name,
            "summary": _check_summary(rows),
        },
    )


@router.get("/logs")
def logs(
    request: Request,
    name: str | None = None,
    tail: int = 100,
    level: str | None = None,
    follow: bool = True,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
    templates=Depends(get_templates),
):
    normalized_level = _normalize_level(level)
    payload = _logs_payload(
        services=services,
        jobs=jobs,
        name=name,
        tail=tail,
        level=normalized_level,
        follow=follow,
    )
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "page_title": "Logs",
            "snapshot": payload["snapshot"],
            "related_links": payload["related_links"],
            "recent_jobs": payload["recent_jobs"],
            "selected_name": name,
            "tail": tail,
            "follow": follow,
            "selected_level": normalized_level or "",
            "levels": ("", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
            "chroots": services.chroots().list(),
        },
    )


@router.get("/logs/events")
async def stream_logs(
    request: Request,
    name: str | None = None,
    tail: int = 100,
    level: str | None = None,
    follow: bool = True,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    return _stream_logs_response(
        request=request,
        services=services,
        jobs=jobs,
        name=name,
        tail=tail,
        level=_normalize_level(level),
        follow=follow,
    )


@router.get("/api/status")
def api_status(name: str | None = None, details: bool = False, services=Depends(get_services)):
    resolved_name = _resolve_target_name(services, name=name)
    rows = _check_rows_payload(services.system().status(resolved_name, details=details), name=resolved_name)
    return {
        "name": resolved_name,
        "details": details,
        "summary": _check_summary(rows),
        "rows": rows,
    }


@router.get("/api/doctor")
def api_doctor(name: str | None = None, services=Depends(get_services)):
    resolved_name = _resolve_target_name(services, name=name)
    rows = _check_rows_payload(services.system().doctor(resolved_name), name=resolved_name)
    return {
        "name": resolved_name,
        "summary": _check_summary(rows),
        "rows": rows,
    }



@router.get("/api/jobs/{job_id}")
def api_job(job_id: str, jobs=Depends(get_jobs)):
    try:
        job = jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return serialize_value(job)

@router.get("/api/chroots")
def api_chroots(services=Depends(get_services)):
    return {
        "items": [serialize_value(chroot) for chroot in services.chroots().list()],
    }

@router.get("/api/logs")
def api_logs(
    name: str | None = None,
    tail: int = 100,
    level: str | None = None,
    follow: bool = False,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    return _logs_api_payload(
        _logs_payload(
            services=services,
            jobs=jobs,
            name=name,
            tail=tail,
            level=_normalize_level(level),
            follow=follow,
        )
    )


@router.get("/api/logs/events")
async def api_stream_logs(
    request: Request,
    name: str | None = None,
    tail: int = 100,
    level: str | None = None,
    follow: bool = True,
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    return _stream_logs_response(
        request=request,
        services=services,
        jobs=jobs,
        name=name,
        tail=tail,
        level=_normalize_level(level),
        follow=follow,
    )


def _resolve_target_name(services: Any, *, name: str | None) -> str:
    if name:
        return name
    summary = services.system().dashboard(tail=5)
    if summary.target_name:
        return summary.target_name
    raise HTTPException(status_code=400, detail="name is required when no default chroot can be resolved")


def _normalize_level(level: str | None) -> str | None:
    return level.upper() if level else None


def _stream_logs_response(
    *,
    request: Request,
    services: Any,
    jobs: Any,
    name: str | None,
    tail: int,
    level: str | None,
    follow: bool,
) -> StreamingResponse:
    async def event_stream():
        while True:
            if await request.is_disconnected():
                return
            payload = _logs_payload(
                services=services,
                jobs=jobs,
                name=name,
                tail=tail,
                level=level,
                follow=follow,
            )
            yield "data: " + json.dumps(_logs_api_payload(payload)) + "\n\n"
            if not follow:
                return
            await asyncio.sleep(0.75)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


def _logs_payload(
    *,
    services: Any,
    jobs: Any,
    name: str | None,
    tail: int,
    level: str | None,
    follow: bool,
) -> dict[str, Any]:
    snapshot = services.system().logs(name, tail=tail, level=level, follow=follow)
    recent_jobs = jobs.list_recent(limit=8, target_name=name, log_path=snapshot.log_file) if hasattr(jobs, "list_recent") else []
    related_links = _merge_related_links(snapshot, recent_jobs)
    return {
        "snapshot": snapshot,
        "related_links": related_links,
        "recent_jobs": recent_jobs,
        "filters": {
            "name": name,
            "tail": tail,
            "level": level or "",
            "follow": follow,
        },
    }


def _logs_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot: LogSnapshot = payload["snapshot"]
    return {
        "snapshot": _snapshot_payload(snapshot),
        "related_links": [_link_payload(link) for link in payload["related_links"]],
        "recent_jobs": [serialize_value(job) for job in payload["recent_jobs"]],
        "filters": payload["filters"],
    }


def _snapshot_payload(snapshot: LogSnapshot) -> dict[str, Any]:
    return {
        "log_file": str(snapshot.log_file),
        "level": snapshot.level or "",
        "target_name": snapshot.target_name,
        "follow": snapshot.follow,
        "text": snapshot.text,
        "entries": [
            {
                "line": entry.line,
                "level": entry.level,
                "links": [{"label": link.label, "href": link.href} for link in entry.links],
            }
            for entry in snapshot.entries
        ],
    }


def _link_payload(link: LogLink) -> dict[str, str]:
    return {
        "label": link.label,
        "href": link.href,
    }


def _check_rows_payload(rows: list[CheckRow], *, name: str) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        action = _next_action(row.next, name=name)
        payload.append(
            {
                "check": row.check,
                "result": row.result,
                "detail": row.detail,
                "next": row.next,
                "next_href": action["href"],
                "next_label": action["label"],
                "result_class": _result_class(row.result),
            }
        )
    return payload


def _check_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pass": sum(1 for row in rows if row["result"] == "PASS"),
        "warn": sum(1 for row in rows if row["result"] == "WARN"),
        "fail": sum(1 for row in rows if row["result"] == "FAIL"),
    }


def _next_action(command: str, *, name: str) -> dict[str, str | None]:
    command = command.strip()
    if not command:
        return {"label": None, "href": None}
    if " logs " in f" {command} ":
        return {"label": "Open logs", "href": f"/logs?name={name}"}
    if " doctor" in f" {command} ":
        return {"label": "Open doctor", "href": f"/doctor?name={name}"}
    if " status" in f" {command} ":
        return {"label": "Open status", "href": f"/status?name={name}"}
    if " start" in f" {command} " or " restart" in f" {command} ":
        return {"label": "Open chroot", "href": f"/chroots/{name}"}
    if "users sync-id" in command:
        username = _extract_username(command)
        if username:
            return {"label": "Open user", "href": f"/chroots/{name}/users/{username}"}
        return {"label": "Open users", "href": f"/chroots/{name}/users"}
    return {"label": None, "href": None}


def _result_class(result: str) -> str:
    normalized = result.upper()
    if normalized == "PASS":
        return "ok"
    if normalized == "WARN":
        return "warn"
    return "bad"


def _merge_related_links(snapshot: LogSnapshot, recent_jobs: list[Any]) -> list[LogLink]:
    links: dict[tuple[str, str], LogLink] = {}

    def add(label: str, href: str) -> None:
        links[(label, href)] = LogLink(label=label, href=href)

    for link in snapshot.related_links:
        add(link.label, link.href)

    for job in recent_jobs:
        target_name = getattr(job, "target_name", None)
        if target_name:
            add(f"Chroot · {target_name}", f"/chroots/{target_name}")
            add(f"Users · {target_name}", f"/chroots/{target_name}/users")
        payload = getattr(job, "result_payload", None)
        for kind, entry_name in _extract_catalog_targets(payload):
            href = f"/tools/{entry_name}" if kind == "tool" else f"/addons/{entry_name}"
            add(f"{kind} · {entry_name}", href)
        username = _extract_username(payload) or _extract_username(getattr(job, "title", ""))
        if username and target_name:
            add(f"User · {username}", f"/chroots/{target_name}/users/{username}")

    return list(links.values())


def _extract_catalog_targets(value: Any) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []

    def walk(item: Any) -> None:
        if item is None:
            return
        if hasattr(item, "kind") and hasattr(item, "name"):
            kind = str(getattr(item, "kind", ""))
            name = str(getattr(item, "name", ""))
            if kind in {"tool", "addon"} and name:
                matches.append((kind, name))
        if hasattr(item, "tool_results") or hasattr(item, "addon_results"):
            walk(getattr(item, "tool_results", ()))
            walk(getattr(item, "addon_results", ()))
        if is_dataclass(item):
            walk(asdict(item))
            return
        if isinstance(item, dict):
            kind = str(item.get("kind", ""))
            name = str(item.get("name", ""))
            if kind in {"tool", "addon"} and name:
                matches.append((kind, name))
            for nested in item.values():
                walk(nested)
            return
        if isinstance(item, (list, tuple, set, frozenset)):
            for nested in item:
                walk(nested)

    walk(value)
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in matches:
        if match in seen:
            continue
        seen.add(match)
        deduped.append(match)
    return deduped


def _extract_username(value: Any) -> str | None:
    if isinstance(value, str):
        return _username_from_text(value)
    username = getattr(value, "username", None)
    if isinstance(username, str) and username:
        return username
    if is_dataclass(value):
        return _extract_username(asdict(value))
    if isinstance(value, dict):
        item = value.get("username")
        if isinstance(item, str) and item:
            return item
    return None


def _username_from_text(text: str) -> str | None:
    parts = text.split()
    if "sync-id" in parts:
        index = parts.index("sync-id")
        if index + 1 < len(parts):
            return parts[index + 1]
    if "user" in parts:
        index = parts.index("user")
        if index + 1 < len(parts):
            return parts[index + 1]
    if "for" in parts:
        index = parts.index("for")
        if index + 1 < len(parts):
            return parts[index + 1]
    return None
