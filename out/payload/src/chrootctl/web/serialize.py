from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def serialize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_event_payload"):
        return serialize_value(value.to_event_payload())
    if is_dataclass(value):
        return {str(key): serialize_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [serialize_value(item) for item in value]
    return value
