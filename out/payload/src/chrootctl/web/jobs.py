from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, is_dataclass, asdict
from pathlib import Path
from typing import Any

from ..models import DisplayRenderable
from ..runtime.common import read_logs

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
TERMINAL_JOB_STATES = frozenset({JOB_SUCCEEDED, JOB_FAILED})


def _serialize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, DisplayRenderable):
        return value.to_display_dict()
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset, deque)):
        return [_serialize(item) for item in value]
    return value


def _extract_next_steps(value: Any) -> tuple[str, ...]:
    next_steps = getattr(value, "next_steps", ())
    if isinstance(next_steps, (list, tuple)):
        return tuple(str(item) for item in next_steps)
    return ()


def _tail_log_lines(log_path: Path | None, tail: int) -> tuple[str, ...]:
    if log_path is None:
        return ()
    text = read_logs(log_path, tail=tail, show_all=False)
    if not text:
        return ()
    return tuple(text.splitlines())


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
            "result_payload": _serialize(self.result_payload),
            "error": self.error,
            "next_steps": list(self.next_steps),
            "log_lines": list(self.log_lines),
            "progress_detail": _serialize(self.progress_detail),
            "progress_events": [_serialize(item) for item in self.progress_events],
            "progress_percent": self.progress_detail.get("percent"),
            "progress_phase": self.progress_detail.get("phase"),
            "complete": self.complete,
            "retry": _serialize(self.retry),
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
    next_steps: tuple[str, ...] = field(default_factory=tuple)
    progress_detail: dict[str, Any] = field(default_factory=dict)
    progress_events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=40))
    retry: dict[str, Any] | None = None

    def snapshot(self, *, tail: int = 50) -> JobSnapshot:
        return JobSnapshot(
            job_id=self.job_id,
            kind=self.kind,
            title=self.title,
            state=self.state,
            progress_text=self.progress_text,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            target_name=self.target_name,
            log_path=self.log_path,
            result_payload=self.result_payload,
            error=self.error,
            next_steps=self.next_steps,
            log_lines=_tail_log_lines(self.log_path, tail),
            progress_detail=dict(self.progress_detail),
            progress_events=tuple(dict(item) for item in self.progress_events),
            retry=dict(self.retry) if isinstance(self.retry, dict) else None,
        )


class WebJobManager:
    def __init__(self, *, max_workers: int = 4) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, _JobRecord] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="chrootctl-web-job")

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
        job_id = uuid.uuid4().hex[:12]
        record = _JobRecord(
            job_id=job_id,
            kind=kind,
            title=title,
            state=JOB_QUEUED,
            progress_text="Queued",
            created_at=time.time(),
            target_name=target_name,
            log_path=log_path,
            retry=dict(retry) if isinstance(retry, dict) else None,
        )
        with self._lock:
            self._jobs[job_id] = record
        self._executor.submit(self._run_job, job_id, runner)
        return record.snapshot()

    def get(self, job_id: str, *, tail: int = 50) -> JobSnapshot:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id].snapshot(tail=tail)

    def list_recent(
        self,
        *,
        limit: int = 10,
        tail: int = 10,
        target_name: str | None = None,
        log_path: Path | None = None,
    ) -> list[JobSnapshot]:
        with self._lock:
            ordered = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
            filtered = [
                job
                for job in ordered
                if (target_name is None or job.target_name == target_name)
                and (log_path is None or job.log_path == log_path)
            ]
            return [job.snapshot(tail=tail) for job in filtered[:limit]]

    def event_payload(self, job_id: str, *, tail: int = 50) -> dict[str, Any]:
        return self.get(job_id, tail=tail).to_event_payload()

    def _run_job(self, job_id: str, runner: Callable[[Callable[[str], None]], Any]) -> None:
        self._update(job_id, state=JOB_RUNNING, started_at=time.time(), progress_text="Starting")

        def progress(update: Any) -> None:
            if isinstance(update, dict):
                detail = {str(key): value for key, value in update.items()}
                text = str(detail.get("message") or detail.get("phase") or "Working")
                self._update_progress(job_id, text=text, detail=detail)
            else:
                self._update_progress(job_id, text=str(update), detail={"message": str(update)})

        try:
            result = runner(progress)
        except Exception as exc:
            self._update(
                job_id,
                state=JOB_FAILED,
                finished_at=time.time(),
                progress_text="Failed",
                error=str(exc),
            )
            return

        self._update(
            job_id,
            state=JOB_SUCCEEDED,
            finished_at=time.time(),
            progress_text="Completed",
            result_payload=result,
            next_steps=_extract_next_steps(result),
        )

    def _update_progress(self, job_id: str, *, text: str, detail: dict[str, Any]) -> None:
        event = dict(detail)
        event.setdefault("message", text)
        event["timestamp"] = time.time()
        with self._lock:
            record = self._jobs[job_id]
            record.progress_text = text
            record.progress_detail = event
            record.progress_events.append(event)

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            record = self._jobs[job_id]
            for key, value in changes.items():
                setattr(record, key, value)
