from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..bridge.redaction import redact_value
from .models import OPERATION_SCHEMA_VERSION, OperationRecord

MAX_EVENT_BYTES = 64 * 1024
MAX_EVENT_COUNT = 2_000
MAX_EVENT_FILE_BYTES = 4 * 1024 * 1024
_TAIL_BLOCK_BYTES = 64 * 1024


class OperationJournal:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records_dir = root / "records"
        self.events_dir = root / "events"
        self.cancel_dir = root / "cancel"
        self.locks_dir = root / "locks"
        for directory in (self.records_dir, self.events_dir, self.cancel_dir, self.locks_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def save(self, record: OperationRecord) -> None:
        operation_id = validate_operation_id(record.operation_id)
        record.schema_version = OPERATION_SCHEMA_VERSION
        target = self.records_dir / f"{operation_id}.json"
        payload = redact_value(record.to_dict())
        _atomic_json_write(target, payload if isinstance(payload, dict) else record.to_dict())

    def load(self, operation_id: str) -> OperationRecord:
        safe_id = validate_operation_id(operation_id)
        target = self.records_dir / f"{safe_id}.json"
        if not target.exists():
            raise KeyError(operation_id)
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("record root is not a JSON object")
            record = OperationRecord.from_dict(value)
            if record.operation_id != safe_id:
                raise ValueError("record operationId does not match its filename")
            return record
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return OperationRecord.corrupt_placeholder(safe_id, f"{exc.__class__.__name__}: {exc}")

    def list_recent(self, *, limit: int = 50, target_name: str | None = None) -> list[OperationRecord]:
        records: list[OperationRecord] = []
        for path in self.records_dir.glob("*.json"):
            try:
                record = self.load(path.stem)
            except (ValueError, KeyError):
                continue
            if target_name is None or record.target_name == target_name:
                records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[: max(1, limit)]

    def append_event(self, operation_id: str, event: dict[str, Any]) -> None:
        safe_id = validate_operation_id(operation_id)
        path = self.events_dir / f"{safe_id}.jsonl"
        sanitized = redact_value(event)
        payload = sanitized if isinstance(sanitized, dict) else {"type": "operation_event", "payload": sanitized}
        encoded = _bounded_event_json(payload, safe_id)
        with path.open("ab") as stream:
            stream.write(encoded)
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        sequence = _event_sequence(payload)
        if path.stat().st_size > MAX_EVENT_FILE_BYTES or sequence > MAX_EVENT_COUNT:
            self._compact_events(path)

    def read_events(self, operation_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        safe_id = validate_operation_id(operation_id)
        path = self.events_dir / f"{safe_id}.jsonl"
        if not path.exists():
            return []
        lines = _tail_lines(path, limit=max(1, min(limit, MAX_EVENT_COUNT)), max_bytes=MAX_EVENT_FILE_BYTES)
        result: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def request_cancel(self, operation_id: str) -> None:
        safe_id = validate_operation_id(operation_id)
        (self.cancel_dir / safe_id).write_text("cancel\n", encoding="utf-8")

    def cancellation_requested(self, operation_id: str) -> bool:
        safe_id = validate_operation_id(operation_id)
        return (self.cancel_dir / safe_id).exists()

    def clear_cancel(self, operation_id: str) -> None:
        safe_id = validate_operation_id(operation_id)
        (self.cancel_dir / safe_id).unlink(missing_ok=True)

    def _compact_events(self, path: Path) -> None:
        lines = _tail_lines(path, limit=MAX_EVENT_COUNT, max_bytes=MAX_EVENT_FILE_BYTES)
        encoded = b"\n".join(line.encode("utf-8", errors="replace") for line in lines)
        if encoded:
            encoded += b"\n"
        _atomic_bytes_write(path, encoded)


def validate_operation_id(value: str) -> str:
    if not value or len(value) > 128:
        raise ValueError("invalid operation identifier")
    if value in {".", ".."}:
        raise ValueError("invalid operation identifier")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in value):
        raise ValueError("invalid operation identifier")
    return value


def _bounded_event_json(event: dict[str, Any], operation_id: str) -> bytes:
    raw = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) <= MAX_EVENT_BYTES:
        return raw
    replacement = {
        "type": str(event.get("type") or "operation_event"),
        "operationId": operation_id,
        "sequence": _event_sequence(event),
        "timestamp": event.get("timestamp"),
        "payload": {
            "message": "Event payload exceeded the journal size limit and was truncated.",
            "truncated": True,
            "originalBytes": len(raw),
            "maxBytes": MAX_EVENT_BYTES,
        },
    }
    return json.dumps(replacement, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _event_sequence(event: dict[str, Any]) -> int:
    try:
        return max(0, int(event.get("sequence") or 0))
    except (TypeError, ValueError):
        return 0


def _tail_lines(path: Path, *, limit: int, max_bytes: int) -> list[str]:
    if limit <= 0:
        return []
    size = path.stat().st_size
    if size <= 0:
        return []
    chunks: list[bytes] = []
    consumed = 0
    newline_count = 0
    with path.open("rb") as stream:
        position = size
        while position > 0 and consumed < max_bytes and newline_count <= limit:
            read_size = min(_TAIL_BLOCK_BYTES, position, max_bytes - consumed)
            if read_size <= 0:
                break
            position -= read_size
            stream.seek(position)
            chunk = stream.read(read_size)
            chunks.append(chunk)
            consumed += len(chunk)
            newline_count += chunk.count(b"\n")
    data = b"".join(reversed(chunks))
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-limit:]


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_bytes_write(path: Path, payload: bytes) -> None:
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
