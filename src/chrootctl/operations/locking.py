from __future__ import annotations

import fcntl
from pathlib import Path
from typing import IO


class OperationBlocked(RuntimeError):
    def __init__(self, lock_key: str, blocking_operation_id: str | None = None) -> None:
        self.lock_key = lock_key
        self.blocking_operation_id = blocking_operation_id
        suffix = f" by operation {blocking_operation_id}" if blocking_operation_id else ""
        super().__init__(f"Operation lock {lock_key!r} is already held{suffix}")


class OperationLock:
    def __init__(self, locks_dir: Path, lock_key: str, operation_id: str) -> None:
        self.path = locks_dir / f"{_safe_lock_key(lock_key)}.lock"
        self.operation_id = operation_id
        self.stream: IO[str] | None = None

    def __enter__(self) -> "OperationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.seek(0)
            blocking = stream.read().strip() or None
            stream.close()
            raise OperationBlocked(self.path.stem.removesuffix(".lock"), blocking) from exc
        stream.seek(0)
        stream.truncate(0)
        stream.write(self.operation_id)
        stream.flush()
        self.stream = stream
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.stream is None:
            return
        self.stream.seek(0)
        self.stream.truncate(0)
        self.stream.flush()
        fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
        self.stream = None


def lock_key_for(scope: str, target_name: str | None) -> str | None:
    if scope == "none":
        return None
    if scope == "global":
        return "global-mutating"
    if scope == "target":
        if not target_name:
            raise ValueError("target-scoped operation requires a target name")
        return f"target-{target_name}"
    raise ValueError(f"unknown lock scope: {scope}")


def _safe_lock_key(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
