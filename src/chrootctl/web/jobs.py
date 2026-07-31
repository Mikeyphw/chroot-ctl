from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..bridge.protocol import serialize_value
from ..operations import OperationManager
from ..operations.models import OperationRecord
from ..runtime.common import read_logs

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted", "blocked"})


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    kind: str
    title: str
    state: str
    progress_text: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    target_name: str | None = None
    log_path: Path | None = None
    result_payload: Any = None
    error: str | None = None
    next_steps: tuple[str, ...] = ()
    log_lines: tuple[str, ...] = ()
    progress_detail: dict[str, Any] = field(default_factory=dict)
    progress_events: tuple[dict[str, Any], ...] = ()
    retry: dict[str, Any] | None = None

    @property
    def complete(self) -> bool:
        return self.state in TERMINAL_JOB_STATES

    def to_event_payload(self, *, log_download_url: str | None = None) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
            "progress_text": self.progress_text,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "target_name": self.target_name,
            "log_path": str(self.log_path) if self.log_path is not None else None,
            "log_download_url": log_download_url,
            "result_payload": serialize_value(self.result_payload),
            "error": self.error,
            "next_steps": list(self.next_steps),
            "log_lines": list(self.log_lines),
            "progress_detail": serialize_value(self.progress_detail),
            "progress_events": serialize_value(self.progress_events),
            "progress_percent": self.progress_detail.get("percent"),
            "progress_phase": self.progress_detail.get("phase"),
            "complete": self.complete,
            "retry": serialize_value(self.retry),
        }


@dataclass(slots=True)
class _JobRecord:
    job_id: str
    kind: str
    title: str
    state: str
    progress_text: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    target_name: str | None = None
    log_path: Path | None = None
    result_payload: Any = None
    error: str | None = None
    next_steps: tuple[str, ...] = ()
    progress_detail: dict[str, Any] = field(default_factory=dict)
    progress_events: tuple[dict[str, Any], ...] = ()
    retry: dict[str, Any] | None = None



class WebJobManager:
    """Compatibility adapter backed by the persistent operation journal.

    The WebUI remains available during the Android migration, but it no longer owns
    an in-memory-only job database. Native Android and the temporary WebUI now observe
    the same durable operation model.
    """

    def __init__(self, *, max_workers: int = 4, state_root: Path | None = None) -> None:
        root = state_root or Path(tempfile.mkdtemp(prefix="chrootctl-web-operations-"))
        self._manager = OperationManager(root)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="chrootctl-operation")
        self._lock = threading.RLock()
        self._jobs: dict[str, _JobRecord] = {}
        self._futures: dict[str, Future[None]] = {}

    def submit(
        self,
        *,
        kind: str,
        title: str,
        runner: Callable[[Callable[[str], None]], Any],
        target_name: str | None = None,
        log_path: Path | None = None,
        retry: dict[str, Any] | None = None,
    ) -> JobSnapshot:
        record = self._manager.create(
            kind=kind,
            title=title,
            target_name=target_name,
            request={"source": "webui-compat"},
            retry=retry,
            log_path=log_path,
            lock_scope="target" if target_name else "global",
        )

        def execute() -> None:
            self._manager.execute(record, lambda progress, cancelled: runner(progress))

        future = self._executor.submit(execute)
        with self._lock:
            self._futures[record.operation_id] = future
        return self._snapshot(record)

    def get(self, job_id: str, *, tail: int = 50) -> JobSnapshot:
        with self._lock:
            injected = self._jobs.get(job_id)
            future = self._futures.get(job_id)
        if injected is not None:
            return self._legacy_snapshot(injected, tail=tail)
        if future is not None and not future.done():
            try:
                future.result(timeout=0.01)
            except FutureTimeoutError:
                pass
        return self._snapshot(self._manager.get(job_id), tail=tail)

    def list_recent(
        self,
        *,
        limit: int = 10,
        tail: int = 10,
        target_name: str | None = None,
        log_path: Path | None = None,
    ) -> list[JobSnapshot]:
        records = self._manager.list_recent(limit=max(limit * 4, limit), target_name=target_name)
        snapshots = [self._snapshot(record, tail=tail) for record in records]
        with self._lock:
            injected = list(self._jobs.values())
        snapshots.extend(self._legacy_snapshot(record, tail=tail) for record in injected)
        snapshots.sort(key=lambda item: item.created_at, reverse=True)
        if target_name is not None:
            snapshots = [item for item in snapshots if item.target_name == target_name]
        if log_path is not None:
            snapshots = [item for item in snapshots if item.log_path == log_path]
        return snapshots[:limit]

    def event_payload(self, job_id: str, *, tail: int = 50) -> dict[str, Any]:
        return self.get(job_id, tail=tail).to_event_payload()

    def cancel(self, job_id: str) -> JobSnapshot:
        return self._snapshot(self._manager.cancel(job_id))

    def _legacy_snapshot(self, record: _JobRecord, *, tail: int = 50) -> JobSnapshot:
        log_lines: tuple[str, ...] = ()
        if record.log_path is not None:
            text = read_logs(record.log_path, tail=tail, show_all=False)
            if text:
                log_lines = tuple(text.splitlines())
        return JobSnapshot(
            job_id=record.job_id,
            kind=record.kind,
            title=record.title,
            state=record.state,
            progress_text=record.progress_text,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            target_name=record.target_name,
            log_path=record.log_path,
            result_payload=record.result_payload,
            error=record.error,
            next_steps=record.next_steps,
            log_lines=log_lines,
            progress_detail=dict(record.progress_detail),
            progress_events=tuple(dict(item) for item in record.progress_events),
            retry=dict(record.retry) if isinstance(record.retry, dict) else None,
        )

    def _snapshot(self, record: OperationRecord, *, tail: int = 50) -> JobSnapshot:
        log_path = Path(record.log_path) if record.log_path else None
        log_lines: tuple[str, ...] = ()
        if log_path is not None:
            text = read_logs(log_path, tail=tail, show_all=False)
            if text:
                log_lines = tuple(text.splitlines())
        return JobSnapshot(
            job_id=record.operation_id,
            kind=record.kind,
            title=record.title,
            state=record.state,
            progress_text=record.progress_text,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            target_name=record.target_name,
            log_path=log_path,
            result_payload=record.result_payload,
            error=record.error,
            next_steps=record.next_steps,
            log_lines=log_lines,
            progress_detail=dict(record.progress_detail),
            progress_events=tuple(dict(item) for item in record.progress_events),
            retry=dict(record.retry) if isinstance(record.retry, dict) else None,
        )
