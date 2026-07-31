from __future__ import annotations

import os
import time

from .journal import OperationJournal
from .models import ACTIVE_STATES


def recover_stale_operations(journal: OperationJournal) -> list[str]:
    recovered: list[str] = []
    for record in journal.list_recent(limit=1000):
        if record.state not in ACTIVE_STATES:
            continue
        if record.pid is not None and _pid_alive(record.pid):
            continue
        record.state = "interrupted"
        record.finished_at = time.time()
        record.progress_text = "Interrupted"
        record.error_code = "PROCESS_DISAPPEARED"
        record.error = "The operation process is no longer running"
        record.next_steps = ("Retry the operation after reviewing its last completed phase.",)
        journal.save(record)
        recovered.append(record.operation_id)
    return recovered


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
