from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import OperationRecord


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
        target = self.records_dir / f"{record.operation_id}.json"
        _atomic_json_write(target, record.to_dict())

    def load(self, operation_id: str) -> OperationRecord:
        target = self.records_dir / f"{_safe_id(operation_id)}.json"
        if not target.exists():
            raise KeyError(operation_id)
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"invalid operation record: {operation_id}")
        return OperationRecord.from_dict(value)

    def list_recent(self, *, limit: int = 50, target_name: str | None = None) -> list[OperationRecord]:
        records: list[OperationRecord] = []
        for path in self.records_dir.glob("*.json"):
            try:
                record = self.load(path.stem)
            except (OSError, ValueError, RuntimeError, KeyError):
                continue
            if target_name is None or record.target_name == target_name:
                records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[: max(1, limit)]

    def append_event(self, operation_id: str, event: dict[str, Any]) -> None:
        path = self.events_dir / f"{_safe_id(operation_id)}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def read_events(self, operation_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        path = self.events_dir / f"{_safe_id(operation_id)}.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, limit) :]
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
        (self.cancel_dir / _safe_id(operation_id)).write_text("cancel\n", encoding="utf-8")

    def cancellation_requested(self, operation_id: str) -> bool:
        return (self.cancel_dir / _safe_id(operation_id)).exists()

    def clear_cancel(self, operation_id: str) -> None:
        (self.cancel_dir / _safe_id(operation_id)).unlink(missing_ok=True)


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


def _safe_id(value: str) -> str:
    if not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value):
        raise ValueError("invalid operation identifier")
    return value
