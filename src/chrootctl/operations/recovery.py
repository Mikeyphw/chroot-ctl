from __future__ import annotations

import time

from ..system import ProcessIdentity, process_identity_matches, terminate_process_identity
from .journal import OperationJournal
from .models import ACTIVE_STATES


def reconcile_operation(journal: OperationJournal, operation_id: str) -> bool:
    """Explicitly reconcile one active record; ordinary reads remain non-mutating."""
    record = journal.load(operation_id)
    if record.state not in ACTIVE_STATES or record.corrupt:
        return False
    identity = _record_identity(record)
    if identity is not None and process_identity_matches(identity):
        return False

    # The bridge host is gone. Clean up only child process groups whose recorded
    # Linux identities still match, preventing PID/PGID reuse from signalling
    # unrelated processes.
    for raw_identity in reversed(record.child_processes):
        child = ProcessIdentity.from_dict(raw_identity)
        if child is not None:
            terminate_process_identity(child)

    cancel_requested = journal.cancellation_requested(record.operation_id)
    record.state = "cancelled" if cancel_requested else "interrupted"
    record.finished_at = time.time()
    if cancel_requested:
        record.progress_text = "Cancelled"
        record.error_code = "CANCELLED"
        record.error = "Cancellation was requested before the operation process exited"
        record.next_steps = ()
    else:
        record.progress_text = "Interrupted"
        record.error_code = "PROCESS_DISAPPEARED"
        record.error = "The recorded operation process identity is no longer running"
        record.next_steps = ("Retry the operation after reviewing its last completed phase.",)
    journal.save(record)
    journal.clear_cancel(record.operation_id)
    return True


def recover_stale_operations(journal: OperationJournal) -> list[str]:
    """Explicitly sweep stale active records; never runs as a side effect of reads."""
    recovered: list[str] = []
    for record in journal.list_recent(limit=1000):
        if record.state not in ACTIVE_STATES or record.corrupt:
            continue
        if reconcile_operation(journal, record.operation_id):
            recovered.append(record.operation_id)
    return recovered


def _record_identity(record: object) -> ProcessIdentity | None:
    pid = getattr(record, "pid", None)
    pgid = getattr(record, "process_group_id", None)
    if not isinstance(pid, int) or not isinstance(pgid, int) or pid <= 0 or pgid <= 0:
        return None
    return ProcessIdentity(
        pid=pid,
        process_group_id=pgid,
        start_time_ticks=getattr(record, "process_start_time", None),
        boot_id=getattr(record, "process_boot_id", None),
    )
