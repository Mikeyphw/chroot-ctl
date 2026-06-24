from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class ErrorAction(BaseModel):
    label: str = Field(..., min_length=1)
    href: str | None = None
    command: str | None = None


class ErrorResponse(BaseModel):
    code: str
    title: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    hints: list[str] = Field(default_factory=list)
    actions: list[ErrorAction] = Field(default_factory=list)
    retryable: bool = False
    status_code: int = 500

    def to_http_payload(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload.pop("status_code", None)
        return payload


@dataclass(slots=True)
class AppError(Exception):
    code: str
    title: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    hints: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    retryable: bool = False
    status_code: int = 400

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            code=self.code,
            title=self.title,
            message=self.message,
            details=dict(self.details),
            hints=list(self.hints),
            actions=[ErrorAction(**item) for item in self.actions],
            retryable=self.retryable,
            status_code=self.status_code,
        )


def error_from_http_exception(status_code: int, detail: Any) -> ErrorResponse:
    if isinstance(detail, ErrorResponse):
        response = detail.model_copy()
        response.status_code = status_code
        return response
    if isinstance(detail, dict):
        known = {
            "code": str(detail.get("code") or f"http_{status_code}"),
            "title": str(detail.get("title") or _default_title(status_code)),
            "message": str(detail.get("message") or detail.get("detail") or _default_message(status_code)),
            "details": detail.get("details") if isinstance(detail.get("details"), dict) else {},
            "hints": [str(item) for item in detail.get("hints", [])],
            "actions": [ErrorAction(**item) for item in detail.get("actions", []) if isinstance(item, dict)],
            "retryable": bool(detail.get("retryable", False)),
            "status_code": status_code,
        }
        return ErrorResponse(**known)
    return ErrorResponse(
        code=f"http_{status_code}",
        title=_default_title(status_code),
        message=str(detail or _default_message(status_code)),
        status_code=status_code,
    )


def _default_title(status_code: int) -> str:
    if status_code == 404:
        return "Not found"
    if status_code == 403:
        return "Forbidden"
    if status_code == 422:
        return "Validation error"
    if status_code >= 500:
        return "Internal error"
    return "Request error"


def _default_message(status_code: int) -> str:
    if status_code == 404:
        return "The requested resource was not found."
    if status_code == 403:
        return "The request is not allowed."
    if status_code == 422:
        return "The request payload is invalid."
    if status_code >= 500:
        return "The request failed because of an internal error."
    return "The request could not be completed."
