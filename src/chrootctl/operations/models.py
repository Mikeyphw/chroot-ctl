from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

OPERATION_SCHEMA_VERSION = 2
TERMINAL_STATES = frozenset({"cancelled", "succeeded", "failed", "interrupted", "blocked"})
ACTIVE_STATES = frozenset({"queued", "running", "cancelling"})


@dataclass(slots=True)
class OperationRecord:
    operation_id: str
    kind: str
    title: str
    state: str = "queued"
    schema_version: int = OPERATION_SCHEMA_VERSION
    target_name: str | None = None
    parent_operation_id: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    phase: str | None = None
    progress_percent: int | None = None
    progress_text: str = "Queued"
    pid: int | None = None
    process_group_id: int | None = None
    process_start_time: int | None = None
    process_boot_id: str | None = None
    child_processes: list[dict[str, Any]] = field(default_factory=list)
    request: dict[str, Any] = field(default_factory=dict)
    result_payload: Any = None
    error: str | None = None
    error_code: str | None = None
    warnings: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    retry: dict[str, Any] | None = None
    log_path: str | None = None
    lock_key: str | None = None
    progress_detail: dict[str, Any] = field(default_factory=dict)
    progress_events: list[dict[str, Any]] = field(default_factory=list)
    event_sequence: int = 0
    corrupt: bool = False
    repair_needed: bool = False
    repair_reason: str | None = None

    @property
    def complete(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "operationId": self.operation_id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
            "targetName": self.target_name,
            "parentOperationId": self.parent_operation_id,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "phase": self.phase,
            "progressPercent": self.progress_percent,
            "progressText": self.progress_text,
            "pid": self.pid,
            "processGroupId": self.process_group_id,
            "processStartTime": self.process_start_time,
            "processBootId": self.process_boot_id,
            "childProcesses": self.child_processes,
            "request": self.request,
            "resultPayload": self.result_payload,
            "error": self.error,
            "errorCode": self.error_code,
            "warnings": list(self.warnings),
            "nextSteps": list(self.next_steps),
            "retry": self.retry,
            "logPath": self.log_path,
            "lockKey": self.lock_key,
            "progressDetail": self.progress_detail,
            "progressEvents": self.progress_events,
            "eventSequence": self.event_sequence,
            "corrupt": self.corrupt,
            "repairNeeded": self.repair_needed,
            "repairReason": self.repair_reason,
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationRecord":
        return cls(
            schema_version=_optional_int(value.get("schemaVersion", value.get("schema_version"))) or 1,
            operation_id=str(value.get("operationId") or value.get("operation_id") or ""),
            kind=str(value.get("kind") or "unknown"),
            title=str(value.get("title") or value.get("kind") or "Operation"),
            state=str(value.get("state") or "queued"),
            target_name=_optional_str(value.get("targetName", value.get("target_name"))),
            parent_operation_id=_optional_str(value.get("parentOperationId", value.get("parent_operation_id"))),
            created_at=float(value.get("createdAt", value.get("created_at", time.time()))),
            started_at=_optional_float(value.get("startedAt", value.get("started_at"))),
            finished_at=_optional_float(value.get("finishedAt", value.get("finished_at"))),
            phase=_optional_str(value.get("phase")),
            progress_percent=_optional_int(value.get("progressPercent", value.get("progress_percent"))),
            progress_text=str(value.get("progressText", value.get("progress_text", "Queued"))),
            pid=_optional_int(value.get("pid")),
            process_group_id=_optional_int(value.get("processGroupId", value.get("process_group_id"))),
            process_start_time=_optional_int(value.get("processStartTime", value.get("process_start_time"))),
            process_boot_id=_optional_str(value.get("processBootId", value.get("process_boot_id"))),
            child_processes=[dict(item) for item in value.get("childProcesses", value.get("child_processes", [])) if isinstance(item, Mapping)],
            request=dict(value.get("request") or {}),
            result_payload=value.get("resultPayload", value.get("result_payload")),
            error=_optional_str(value.get("error")),
            error_code=_optional_str(value.get("errorCode", value.get("error_code"))),
            warnings=tuple(str(item) for item in value.get("warnings", [])),
            next_steps=tuple(str(item) for item in value.get("nextSteps", value.get("next_steps", []))),
            retry=dict(value["retry"]) if isinstance(value.get("retry"), Mapping) else None,
            log_path=_optional_str(value.get("logPath", value.get("log_path"))),
            lock_key=_optional_str(value.get("lockKey", value.get("lock_key"))),
            progress_detail=dict(value.get("progressDetail", value.get("progress_detail", {})) or {}),
            progress_events=[
                dict(item)
                for item in value.get("progressEvents", value.get("progress_events", []))
                if isinstance(item, Mapping)
            ],
            event_sequence=_optional_int(value.get("eventSequence", value.get("event_sequence"))) or 0,
            corrupt=bool(value.get("corrupt", False)),
            repair_needed=bool(value.get("repairNeeded", value.get("repair_needed", False))),
            repair_reason=_optional_str(value.get("repairReason", value.get("repair_reason"))),
        )

    @classmethod
    def corrupt_placeholder(cls, operation_id: str, reason: str) -> "OperationRecord":
        return cls(
            operation_id=operation_id,
            kind="journal.corrupt",
            title="Corrupt operation record",
            state="blocked",
            progress_text="Repair required",
            error_code="CORRUPT_OPERATION_RECORD",
            error=reason,
            next_steps=("Inspect or remove the corrupt operation record before retrying the action.",),
            corrupt=True,
            repair_needed=True,
            repair_reason=reason,
        )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
