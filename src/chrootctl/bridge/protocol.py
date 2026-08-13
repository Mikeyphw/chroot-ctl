from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from ..models import DisplayRenderable
from .redaction import redact_value

PROTOCOL_VERSION = 1
MAX_BRIDGE_REQUEST_BYTES = 1024 * 1024
MAX_BRIDGE_JSON_DEPTH = 24
MAX_BRIDGE_STRING_LENGTH = 16 * 1024
MAX_BRIDGE_ARRAY_LENGTH = 2048
MAX_BRIDGE_OBJECT_KEYS = 512
_REQUEST_TOP_LEVEL_KEYS = frozenset({"protocolVersion", "requestId", "operation", "payload"})
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,80}$")


class BridgeProtocolError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class BridgeRequest:
    protocol_version: int
    request_id: str
    operation: str
    payload: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BridgeRequest":
        unknown = sorted(str(key) for key in value.keys() if str(key) not in _REQUEST_TOP_LEVEL_KEYS)
        if unknown:
            raise BridgeProtocolError("UNKNOWN_REQUEST_FIELD", "Request contains unknown top-level field(s)", details={"fields": unknown})
        version = value.get("protocolVersion")
        if version != PROTOCOL_VERSION:
            raise BridgeProtocolError(
                "UNSUPPORTED_PROTOCOL_VERSION",
                f"Protocol version {version!r} is not supported",
                details={"supported": [PROTOCOL_VERSION]},
            )
        request_id = str(value.get("requestId") or "").strip()
        if not _REQUEST_ID_RE.fullmatch(request_id):
            raise BridgeProtocolError("INVALID_REQUEST_ID", "requestId must contain 1-128 safe identifier characters")
        operation = str(value.get("operation") or "").strip()
        if not operation:
            raise BridgeProtocolError("MISSING_OPERATION", "operation is required")
        if not _OPERATION_RE.fullmatch(operation):
            raise BridgeProtocolError("INVALID_OPERATION", "operation must be a safe allowlisted identifier")
        payload = value.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise BridgeProtocolError("INVALID_PAYLOAD", "payload must be a JSON object")
        _validate_json_shape(payload, field="payload")
        return cls(version, request_id, operation, {str(key): item for key, item in payload.items()})

    @classmethod
    def from_json(cls, raw: str) -> "BridgeRequest":
        if len(raw.encode("utf-8", errors="ignore")) > MAX_BRIDGE_REQUEST_BYTES:
            raise BridgeProtocolError(
                "REQUEST_TOO_LARGE",
                f"Bridge request must not exceed {MAX_BRIDGE_REQUEST_BYTES} bytes",
                details={"maxBytes": MAX_BRIDGE_REQUEST_BYTES},
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BridgeProtocolError("INVALID_JSON", f"Request is not valid JSON: {exc.msg}") from exc
        if not isinstance(value, Mapping):
            raise BridgeProtocolError("INVALID_REQUEST", "Request must be a JSON object")
        _validate_json_shape(value, field="request")
        return cls.from_mapping(value)


@dataclass(frozen=True, slots=True)
class BridgeResponse:
    request_id: str
    ok: bool
    data: Any = None
    error: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": self.request_id,
            "ok": self.ok,
            "data": serialize_value(self.data),
            "error": serialize_value(self.error),
            "warnings": list(self.warnings),
            "nextSteps": list(self.next_steps),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def success(
        cls,
        request_id: str,
        data: Any,
        *,
        warnings: tuple[str, ...] = (),
        next_steps: tuple[str, ...] = (),
    ) -> "BridgeResponse":
        return cls(request_id=request_id, ok=True, data=data, warnings=warnings, next_steps=next_steps)

    @classmethod
    def failure(cls, request_id: str, error: BridgeProtocolError | Exception) -> "BridgeResponse":
        if isinstance(error, BridgeProtocolError):
            payload = {"code": error.code, "message": _safe_error_message(error.message), "details": serialize_value(redact_value(error.details))}
        else:
            payload = {"code": "INTERNAL_ERROR", "message": _safe_error_message(str(error) or error.__class__.__name__), "details": {}}
        return cls(request_id=request_id, ok=False, error=payload)


def event_payload(event_type: str, *, operation_id: str, request_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "type": event_type,
        "operationId": operation_id,
        "requestId": request_id,
        "timestamp": time.time(),
        "payload": serialize_value(dict(payload or {})),
    }


def serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, DisplayRenderable):
        return serialize_value(value.to_display_dict())
    if is_dataclass(value):
        return {str(key): serialize_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset, deque)):
        return [serialize_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return serialize_value(to_dict())
    return str(value)


def extract_request_id_safely(raw: str) -> str | None:
    try:
        value = json.loads(raw[:MAX_BRIDGE_REQUEST_BYTES])
    except Exception:
        return None
    if not isinstance(value, Mapping):
        return None
    request_id = str(value.get("requestId") or "").strip()
    return request_id if _REQUEST_ID_RE.fullmatch(request_id) else None


def _safe_error_message(message: str) -> str:
    redacted = redact_value(message)
    text = str(redacted).strip() or "Bridge request failed"
    return " ".join(text.split())[:512]


def _validate_json_shape(value: Any, *, field: str, depth: int = 0) -> None:
    if depth > MAX_BRIDGE_JSON_DEPTH:
        raise BridgeProtocolError("REQUEST_TOO_DEEP", f"{field} exceeds maximum JSON nesting depth")
    if isinstance(value, str):
        if len(value) > MAX_BRIDGE_STRING_LENGTH:
            raise BridgeProtocolError("REQUEST_STRING_TOO_LONG", f"{field} exceeds maximum string length")
        return
    if value is None or isinstance(value, (int, float, bool)):
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_BRIDGE_OBJECT_KEYS:
            raise BridgeProtocolError("REQUEST_OBJECT_TOO_LARGE", f"{field} has too many keys")
        for key, item in value.items():
            if not isinstance(key, str):
                raise BridgeProtocolError("INVALID_JSON_KEY", f"{field} contains a non-string key")
            if len(key) > 256:
                raise BridgeProtocolError("REQUEST_KEY_TOO_LONG", f"{field} contains an overlong key")
            _validate_json_shape(item, field=f"{field}.{key}", depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_BRIDGE_ARRAY_LENGTH:
            raise BridgeProtocolError("REQUEST_ARRAY_TOO_LARGE", f"{field} has too many array items")
        for index, item in enumerate(value):
            _validate_json_shape(item, field=f"{field}[{index}]", depth=depth + 1)
        return
    raise BridgeProtocolError("INVALID_JSON_VALUE", f"{field} contains unsupported JSON value type")
