from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/ksu", tags=["ksu"])


def _status(app: Any) -> dict[str, Any]:
    security = app.state.web_security
    lifecycle = app.state.services.lifecycle().status(host=security.bind_host, port=security.bind_port)
    return {
        "webui": lifecycle["state"],
        "server": {
            "host": security.bind_host,
            "port": security.bind_port,
            "url": lifecycle["url"],
        },
        "module": lifecycle["module"],
        "python": lifecycle["python"],
        "control_file": lifecycle["control_file"],
        "pid_file": lifecycle["pid_file"],
        "checked_at": int(time.time()),
    }


@router.get("/status")
def status(request: Request) -> JSONResponse:
    return JSONResponse(_status(request.app))


@router.post("/control")
async def control(request: Request) -> JSONResponse:
    data = await request.json()
    action = str(data.get("action", "")).strip().lower()
    lifecycle = request.app.state.services.lifecycle()
    try:
        result = {
            "start": lifecycle.start_webui,
            "stop": lifecycle.stop_webui,
            "restart": lifecycle.restart_webui,
        }[action]()
    except KeyError:
        return JSONResponse({"ok": False, "error": "unsupported action"}, status_code=400)
    return JSONResponse(result)


@router.get("")
def ui(request: Request):
    templates = request.app.state.templates
    security = request.app.state.web_security
    return templates.TemplateResponse(
        request,
        "ksu.html",
        {
            "status_url": "/ksu/status",
            "control_url": "/ksu/control",
            "open_url": f"http://{security.bind_host}:{security.bind_port}",
        },
    )
