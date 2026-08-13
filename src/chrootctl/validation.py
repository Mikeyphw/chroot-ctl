from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SAFE_CATALOG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._:-]{0,127}$")
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}[$]?$")


def _clean_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} is required")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError(f"{field} must be a single-line value")
    return text


def _validate_basename(value: Any, *, field: str, pattern: re.Pattern[str]) -> str:
    text = _clean_text(value, field=field)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"{field} must be a safe basename")
    if not pattern.fullmatch(text):
        raise ValueError(f"invalid {field}: {value!r}")
    return text


def validate_chroot_name(name: Any, *, field: str = "chroot name") -> str:
    return _validate_basename(name, field=field, pattern=_SAFE_NAME_RE)


def validate_snapshot_name(name: Any, *, field: str = "snapshot name") -> str:
    return _validate_basename(name, field=field, pattern=_SAFE_SNAPSHOT_RE)


def validate_catalog_name(name: Any, *, field: str = "catalog name") -> str:
    return _validate_basename(name, field=field, pattern=_SAFE_CATALOG_RE)


def validate_service_name(name: Any, *, field: str = "service name") -> str:
    return _validate_basename(name, field=field, pattern=_SERVICE_NAME_RE)


def validate_username(username: Any, *, field: str = "username") -> str:
    text = _clean_text(username, field=field)
    if not _USERNAME_RE.fullmatch(text):
        raise ValueError(f"invalid {field}: {username!r}")
    return text


def strict_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a JSON boolean")


def optional_bool(mapping: Mapping[str, Any], *keys: str, default: bool = False, field: str | None = None) -> bool:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return strict_bool(mapping[key], field=field or key)
    return default


def bounded_int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def optional_bounded_int(mapping: Mapping[str, Any], key: str, *, default: int, minimum: int, maximum: int) -> int:
    if key not in mapping or mapping[key] is None:
        return default
    return bounded_int(mapping[key], field=key, minimum=minimum, maximum=maximum)


def strict_string_list(value: Any, *, field: str, allow_empty: bool = True) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON array of strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field}[{index}] must be a string")
        text = item.strip()
        if not text and not allow_empty:
            raise ValueError(f"{field}[{index}] must not be empty")
        if text:
            result.append(text)
    return tuple(result)


def unique_catalog_names(value: Any, *, field: str = "names") -> tuple[str, ...]:
    names = strict_string_list(value, field=field, allow_empty=False)
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        safe = validate_catalog_name(name, field=f"{field} item")
        if safe in seen:
            raise ValueError(f"duplicate {field} item: {safe}")
        seen.add(safe)
        unique.append(safe)
    return tuple(unique)


def validate_relative_chroot_path(value: Any, *, field: str = "path") -> str:
    text = _clean_text(value, field=field)
    path = PurePosixPath(text)
    if path.is_absolute():
        raise ValueError(f"{field} must be relative to the chroot root")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must not contain empty, current, or parent path segments")
    return text


def validate_safe_archive_name(value: Any, *, field: str = "archive") -> str:
    text = _clean_text(value, field=field)
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError(f"{field} must be a single-line value")
    return text


def no_duplicate_top_level_functions(paths: Iterable[Any]) -> dict[str, list[str]]:
    import ast
    from pathlib import Path

    duplicates: dict[str, list[str]] = {}
    for raw_path in paths:
        path = Path(raw_path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        seen: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seen[node.name] = seen.get(node.name, 0) + 1
        repeated = sorted(name for name, count in seen.items() if count > 1)
        if repeated:
            duplicates[str(path)] = repeated
    return duplicates
