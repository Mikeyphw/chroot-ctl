from __future__ import annotations

import re
from typing import Any, Mapping

_SECRET_KEYS = frozenset({
    "access_token",
    "authorization",
    "cookie",
    "csrf",
    "password",
    "passphrase",
    "secret",
    "token",
})
_BEARER_RE = re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/-]+=*")


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if _is_secret_key(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return _BEARER_RE.sub(lambda match: f"{match.group(1)} <redacted>", value)
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SECRET_KEYS or normalized.endswith("_password") or normalized.endswith("_token")
