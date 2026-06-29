from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..errors import AppError, ErrorResponse, error_from_http_exception

logger = logging.getLogger(__name__)


def install_exception_handlers(app) -> None:
    app.exception_handler(AppError)(_handle_app_error)
    app.exception_handler(HTTPException)(_handle_http_exception)
    app.exception_handler(StarletteHTTPException)(_handle_http_exception)
    app.exception_handler(Exception)(_handle_unexpected_exception)


async def _handle_app_error(request: Request, exc: AppError):
    response = exc.to_response()
    _log_error(request, response)
    return _render_error(request, response)


async def _handle_http_exception(request: Request, exc: HTTPException | StarletteHTTPException):
    response = error_from_http_exception(exc.status_code, exc.detail)
    _log_error(request, response)
    return _render_error(request, response)


async def _handle_unexpected_exception(request: Request, exc: Exception):
    response = ErrorResponse(
        code="internal_error",
        title="Internal error",
        message="The page could not be loaded because of an unexpected internal error.",
        details={"path": request.url.path, "method": request.method},
        hints=["Open the logs page for technical details.", "Retry the action after checking system readiness."],
        actions=[{"label": "Open dashboard", "href": "/"}, {"label": "Open logs", "href": "/logs"}],
        retryable=True,
        status_code=500,
    )
    logger.exception("Unhandled request error", extra={"path": request.url.path, "method": request.method})
    return _render_error(request, response)


def _render_error(request: Request, response: ErrorResponse):
    if _wants_json(request):
        return JSONResponse(status_code=response.status_code, content={"error": response.to_http_payload()})
    templates = getattr(request.app.state, "templates", None)
    if templates is None:
        return PlainTextResponse(f"{response.title}: {response.message}", status_code=response.status_code)
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "page_title": response.title,
            "error": response,
        },
        status_code=response.status_code,
    )


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return request.url.path.startswith("/api") or "application/json" in accept


def _log_error(request: Request, response: ErrorResponse) -> None:
    logger.warning(
        "Request failed",
        extra={"path": request.url.path, "method": request.method, "error_code": response.code, "status_code": response.status_code},
    )
