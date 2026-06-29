from __future__ import annotations

from pathlib import Path

from chrootctl.web.jobs import JOB_FAILED, JOB_SUCCEEDED, WebJobManager


def test_web_job_manager_tracks_success_lifecycle(tmp_path: Path) -> None:
    log_path = tmp_path / "job.log"
    log_path.write_text("first\nsecond\n", encoding="utf-8")
    manager = WebJobManager(max_workers=1)
    snapshot = manager.submit(
        kind="install",
        title="Install work",
        log_path=log_path,
        runner=lambda progress: _run_success(progress),
    )
    assert snapshot.state in {"queued", "running", "succeeded"}
    final = _wait_for_terminal_state(manager, snapshot.job_id)
    assert final.state == JOB_SUCCEEDED
    assert final.next_steps == ("chrootctl start",)
    assert final.log_lines == ("first", "second")


def test_web_job_manager_tracks_failed_jobs() -> None:
    manager = WebJobManager(max_workers=1)
    snapshot = manager.submit(
        kind="remove",
        title="Remove work",
        runner=lambda progress: _run_failure(progress),
    )
    final = _wait_for_terminal_state(manager, snapshot.job_id)
    assert final.state == JOB_FAILED
    assert final.error == "boom"


def _run_success(progress):
    progress("Preparing install")

    class Result:
        next_steps = ("chrootctl start",)

    return Result()


def _run_failure(progress):
    progress("About to fail")
    raise RuntimeError("boom")


def _wait_for_terminal_state(manager: WebJobManager, job_id: str, attempts: int = 100):
    for _ in range(attempts):
        snapshot = manager.get(job_id)
        if snapshot.complete:
            return snapshot
    raise AssertionError("job did not complete")
