from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from chrootctl.runtime import session


class Controller:
    def status(self, *, verbose: bool):
        return [{"source": "/proc", "target": "/proc", "type": "bind", "mounted": "yes", "target_exists": "yes", "source_exists": "yes"}]

    def doctor(self):
        return [
            {"check": "busybox", "status": "missing", "detail": ""},
            {"check": "root", "status": "warning", "detail": "sudo required"},
        ]


class Registry:
    def __init__(self, record):
        self._record = record

    def get(self, name: str):
        return self._record


def build_context(tmp_path: Path, *, details: bool, record):
    return SimpleNamespace(
        args=argparse.Namespace(details=details, tail=10, all=False, follow=False, level=None, command="status", json=False),
        controller=Controller(),
        registry=Registry(record),
        config=SimpleNamespace(distro_name="ubuntu", log_file=tmp_path / "chrootctl.log"),
    )


def test_handle_status_renders_actionable_mount_rows_and_verbose_chroot_summary(monkeypatch, tmp_path: Path) -> None:
    context = build_context(
        tmp_path,
        details=True,
        record={"phase": "finalize", "installed": True, "distro": "ubuntu"},
    )
    rendered_tables: list[tuple[str, object]] = []
    rendered_panels: list[tuple[str, object]] = []

    monkeypatch.setattr(session, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(session, "emit_table", lambda context, title, rows: rendered_tables.append((title, rows)))
    monkeypatch.setattr(session, "emit_panel", lambda context, title, data: rendered_panels.append((title, data)))

    session.handle_status(context)

    assert rendered_tables == [
        (
            "Mount Status",
            [
                {
                    "check": "/proc",
                    "result": "PASS",
                    "detail": "/proc from /proc type=bind target_exists=yes source_exists=yes",
                    "next": "",
                }
            ],
        )
    ]
    assert rendered_panels == [
        (
            "Chroot",
            {
                "name": "ubuntu",
                "phase": "finalize",
                "installed": "True",
                "next": "chrootctl start",
            },
        )
    ]


def test_handle_doctor_renders_pass_warn_fail_rows_with_next_steps(monkeypatch, tmp_path: Path) -> None:
    context = build_context(
        tmp_path,
        details=False,
        record={"phase": "bootstrap", "installed": False, "distro": "ubuntu"},
    )
    rendered_tables: list[tuple[str, object]] = []

    monkeypatch.setattr(session, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(session, "emit_table", lambda context, title, rows: rendered_tables.append((title, rows)))

    session.handle_doctor(context)

    title, rows = rendered_tables[0]
    assert title == "Doctor"
    assert rows[0] == {"check": "busybox", "result": "FAIL", "detail": "", "next": "pkg install busybox"}
    assert rows[1] == {"check": "root", "result": "WARN", "detail": "sudo required", "next": "chrootctl mount"}
    assert rows[2] == {
        "check": "registry",
        "result": "PASS",
        "detail": "phase=bootstrap installed=False",
        "next": "chrootctl install ubuntu --resume",
    }
    assert rows[3]["check"] == "log_file"
    assert rows[3]["result"] == "WARN"
    assert rows[3]["next"] == "chrootctl logs --all"


def test_handle_logs_prints_panel_with_filter_and_path(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path, details=False, record=None)
    context.args.command = "logs"
    context.args.level = "ERROR"
    printed = []

    monkeypatch.setattr(session, "read_logs", lambda *args, **kwargs: "")
    monkeypatch.setattr(session.console, "print", lambda panel: printed.append(panel))

    session.handle_logs(context)

    assert len(printed) == 1
    assert printed[0].title == "Logs · chrootctl.log"
    assert printed[0].renderable.plain == (
        f"path: {tmp_path / 'chrootctl.log'}\n"
        "level: ERROR\n"
        "mode: snapshot\n\n"
        "no logs available"
    )


def test_handle_logs_follows_new_lines(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path, details=False, record=None)
    context.args.command = "logs"
    context.args.follow = True
    printed = []

    monkeypatch.setattr(session, "read_logs", lambda *args, **kwargs: "2026-01-01 INFO chrootctl: boot")
    monkeypatch.setattr(session, "follow_logs", lambda *args, **kwargs: iter(["2026-01-01 ERROR chrootctl: boom"]))
    monkeypatch.setattr(session.console, "print", lambda value: printed.append(value))

    session.handle_logs(context)

    assert printed[0].title == "Logs · chrootctl.log"
    assert printed[1] == "2026-01-01 ERROR chrootctl: boom"


def test_handle_start_execs_interactive_session_without_spinner(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path, details=False, record=None)
    context.args = argparse.Namespace(login=True, root_login=False, command="start", json=False)
    calls: list[tuple[str, bool]] = []

    class StartController(Controller):
        def start_interactive(self, *, login: bool, root_login: bool, x11: bool = False):
            assert login is True
            assert root_login is False
            raise SystemExit(0)

    context.controller = StartController()

    def fake_progress_call(description, fn, *, interactive=False):
        calls.append((description, interactive))
        return fn()

    monkeypatch.setattr(session, "progress_call", fake_progress_call)

    with pytest.raises(SystemExit) as exc:
        session.handle_start(context)

    assert exc.value.code == 0
    assert calls == []


def test_handle_exec_skips_spinner_for_terminal_owned_exec(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path, details=False, record=None)
    context.args = argparse.Namespace(argv=["--", "bash"], root=False, exec_text=None, command="exec", json=False)
    calls: list[tuple[str, bool]] = []

    class ExecController(Controller):
        def exec(self, *, root: bool, argv, command, x11: bool = False):
            assert root is False
            assert argv == ["bash"]
            assert command is None
            return 0

    context.controller = ExecController()

    def fake_progress_call(description, fn, *, interactive=False):
        calls.append((description, interactive))
        return fn()

    monkeypatch.setattr(session, "progress_call", fake_progress_call)

    with pytest.raises(SystemExit) as exc:
        session.handle_exec(context)

    assert exc.value.code == 0
    assert calls == []


class _RegistryWithWrites:
    def __init__(self, record):
        self._record = record
        self.upserts: list[dict[str, object]] = []

    def get(self, name: str):
        return self._record

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        self._record = dict(kwargs)
        self._record["metadata"] = kwargs.get("metadata", {})


class _Runner:
    dry_run = True


def test_handle_start_auto_records_existing_clipboard_wrappers(monkeypatch, tmp_path: Path) -> None:
    chroot_base = tmp_path / "ubuntu"
    for rel in ("usr/local/bin/termux-clip", "usr/local/bin/xsel", "usr/local/bin/xclip"):
        path = chroot_base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    registry = _RegistryWithWrites(
        {
            "name": "ubuntu",
            "distro": "ubuntu",
            "path": str(chroot_base),
            "phase": "finalize",
            "installed": True,
            "arch": None,
            "release_name": None,
            "version": None,
            "metadata": {},
        }
    )
    controller_calls = []

    class _Controller(Controller):
        def start_interactive(self, *, login: bool, root_login: bool, x11: bool = False):
            controller_calls.append((login, root_login, x11))
            raise SystemExit(0)

    context = SimpleNamespace(
        args=argparse.Namespace(login=False, root_login=False, x11=False, json=False),
        controller=_Controller(),
        registry=registry,
        runner=_Runner(),
        logger=None,
        config=SimpleNamespace(distro_name="ubuntu", chroot_base=chroot_base),
    )

    monkeypatch.setattr(session, "progress_call", lambda description, fn, **kwargs: fn())

    with pytest.raises(SystemExit) as exc:
        session.handle_start(context)

    assert exc.value.code == 0

    assert controller_calls == [(False, False, False)]
    assert registry.upserts
    assert registry.upserts[-1]["metadata"]["tools"] == "setup-clipboard"


def test_handle_start_auto_applies_clipboard_tool_when_missing(monkeypatch, tmp_path: Path) -> None:
    chroot_base = tmp_path / "ubuntu"
    registry = _RegistryWithWrites(
        {
            "name": "ubuntu",
            "distro": "ubuntu",
            "path": str(chroot_base),
            "phase": "finalize",
            "installed": True,
            "arch": None,
            "release_name": None,
            "version": None,
            "metadata": {},
        }
    )
    applied: list[list[str]] = []

    class _Controller(Controller):
        def start_interactive(self, *, login: bool, root_login: bool, x11: bool = False):
            raise SystemExit(0)

    context = SimpleNamespace(
        args=argparse.Namespace(login=False, root_login=False, x11=False, json=False),
        controller=_Controller(),
        registry=registry,
        runner=_Runner(),
        logger=None,
        config=SimpleNamespace(distro_name="ubuntu", chroot_base=chroot_base),
    )

    monkeypatch.setattr(session, "progress_call", lambda description, fn, **kwargs: fn())
    monkeypatch.setattr(session, "apply_catalog_entries", lambda **kwargs: applied.append(kwargs["names"]) or [])

    with pytest.raises(SystemExit) as exc:
        session.handle_start(context)

    assert exc.value.code == 0

    assert applied == [["setup-clipboard"]]
