from __future__ import annotations

import os
import signal
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from ..bridge.protocol import serialize_value
from ..bridge.redaction import redact_value
from .journal import OperationJournal
from .locking import OperationBlocked, OperationLock, lock_key_for
from .models import OperationRecord, TERMINAL_STATES
from .recovery import recover_stale_operations

ProgressCallback = Callable[[Any], None]
OperationRunner = Callable[[ProgressCallback, Callable[[], bool]], Any]
EventEmitter = Callable[[dict[str, Any]], None]


class OperationCancelled(RuntimeError):
    pass


class OperationManager:
    def __init__(self, root: Path) -> None:
        self.journal = OperationJournal(root)
        recover_stale_operations(self.journal)

    def create(
        self,
        *,
        kind: str,
        title: str,
        target_name: str | None = None,
        request: dict[str, Any] | None = None,
        retry: dict[str, Any] | None = None,
        log_path: Path | None = None,
        lock_scope: str = "none",
        operation_id: str | None = None,
    ) -> OperationRecord:
        identifier = operation_id or uuid.uuid4().hex[:16]
        lock_key = lock_key_for(lock_scope, target_name)
        record = OperationRecord(
            operation_id=identifier,
            kind=kind,
            title=title,
            target_name=target_name,
            request=redact_value(dict(request or {})),
            retry=redact_value(dict(retry)) if retry is not None else None,
            log_path=str(log_path) if log_path is not None else None,
            lock_key=lock_key,
        )
        self.journal.clear_cancel(identifier)
        self.journal.save(record)
        self._event(record, "operation_queued", {"state": record.state})
        return record

    def execute(self, record: OperationRecord, runner: OperationRunner, *, emit: EventEmitter | None = None) -> OperationRecord:
        lock = OperationLock(self.journal.locks_dir, record.lock_key, record.operation_id) if record.lock_key else nullcontext()
        try:
            with lock:
                self._set_running(record)
                self._event(record, "operation_started", {"state": record.state}, emit)

                def cancelled() -> bool:
                    return self.journal.cancellation_requested(record.operation_id)

                def progress(update: Any) -> None:
                    if cancelled():
                        raise OperationCancelled("Cancellation requested")
                    detail = dict(update) if isinstance(update, dict) else {"message": str(update)}
                    text = str(detail.get("message") or detail.get("phase") or "Working")
                    percent = detail.get("percent")
                    record.progress_text = text
                    record.phase = str(detail.get("phase")) if detail.get("phase") is not None else record.phase
                    record.progress_percent = _coerce_percent(percent)
                    event = {str(key): serialize_value(item) for key, item in detail.items()}
                    event.setdefault("message", text)
                    event["timestamp"] = time.time()
                    record.progress_detail = event
                    record.progress_events = (record.progress_events + [event])[-80:]
                    self.journal.save(record)
                    self._event(record, "operation_progress", event, emit)

                if cancelled():
                    raise OperationCancelled("Cancellation requested")
                result = runner(progress, cancelled)
                if cancelled():
                    raise OperationCancelled("Cancellation requested")
                record.state = "succeeded"
                record.finished_at = time.time()
                record.progress_text = "Completed"
                record.progress_percent = 100
                record.result_payload = serialize_value(result)
                record.next_steps = _extract_next_steps(result)
                self.journal.save(record)
                self._event(record, "operation_succeeded", {"result": record.result_payload}, emit)
                return record
        except OperationBlocked as exc:
            record.state = "blocked"
            record.finished_at = time.time()
            record.progress_text = "Blocked"
            record.error_code = "OPERATION_BLOCKED"
            record.error = str(exc)
            record.next_steps = tuple(filter(None, [
                f"Review operation {exc.blocking_operation_id}." if exc.blocking_operation_id else None,
                "Retry after the conflicting operation finishes.",
            ]))
            self.journal.save(record)
            self._event(record, "operation_blocked", {"message": record.error}, emit)
            return record
        except OperationCancelled as exc:
            record.state = "cancelled"
            record.finished_at = time.time()
            record.progress_text = "Cancelled"
            record.error_code = "CANCELLED"
            record.error = str(exc)
            self.journal.save(record)
            self._event(record, "operation_cancelled", {"message": record.error}, emit)
            return record
        except Exception as exc:
            record.state = "failed"
            record.finished_at = time.time()
            record.progress_text = "Failed"
            record.error_code = getattr(exc, "code", None) or "OPERATION_FAILED"
            record.error = str(exc) or exc.__class__.__name__
            self.journal.save(record)
            self._event(record, "operation_failed", {"code": record.error_code, "message": record.error}, emit)
            return record
        finally:
            self.journal.clear_cancel(record.operation_id)

    def get(self, operation_id: str, *, event_limit: int = 200) -> OperationRecord:
        record = self.journal.load(operation_id)
        record.progress_events = self.journal.read_events(operation_id, limit=event_limit)
        return record

    def list_recent(self, *, limit: int = 50, target_name: str | None = None) -> list[OperationRecord]:
        return self.journal.list_recent(limit=limit, target_name=target_name)

    def cancel(self, operation_id: str) -> OperationRecord:
        record = self.journal.load(operation_id)
        if record.state in TERMINAL_STATES:
            return record
        self.journal.request_cancel(operation_id)
        record.state = "cancelling"
        record.progress_text = "Cancelling"
        self.journal.save(record)
        self._event(record, "operation_cancelling", {})
        pgid = record.process_group_id
        if pgid and record.pid != os.getpid():
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        return record

    def _set_running(self, record: OperationRecord) -> None:
        record.state = "running"
        record.started_at = time.time()
        record.progress_text = "Starting"
        record.pid = os.getpid()
        record.process_group_id = _current_process_group()
        self.journal.save(record)

    def _event(self, record: OperationRecord, event_type: str, payload: dict[str, Any], emit: EventEmitter | None = None) -> None:
        event = {
            "type": event_type,
            "operationId": record.operation_id,
            "timestamp": time.time(),
            "payload": redact_value(serialize_value(payload)),
        }
        self.journal.append_event(record.operation_id, event)
        if emit is not None:
            emit(event)


def detach_process_group() -> int:
    try:
        os.setsid()
    except PermissionError:
        pass
    return _current_process_group()


def _current_process_group() -> int:
    try:
        return os.getpgrp()
    except OSError:
        return os.getpid()


def _coerce_percent(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return None


def _extract_next_steps(value: Any) -> tuple[str, ...]:
    next_steps = getattr(value, "next_steps", ())
    if isinstance(next_steps, (list, tuple)):
        return tuple(str(item) for item in next_steps)
    if isinstance(value, dict) and isinstance(value.get("next_steps"), (list, tuple)):
        return tuple(str(item) for item in value["next_steps"])
    return ()
