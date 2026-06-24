from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from ..services import ServiceContainer
from .jobs import WebJobManager


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def get_jobs(request: Request) -> WebJobManager:
    return request.app.state.jobs


def resolve_log_path(services: object, *, name: str | None = None, username: str | None = None) -> Path | None:
    config_for = getattr(services, "config_for", None)
    if not callable(config_for):
        return None
    config = config_for(name, username=username)
    return getattr(config, "log_file", None)
