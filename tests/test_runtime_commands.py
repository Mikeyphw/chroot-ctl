from __future__ import annotations

import argparse
import logging

import pytest

from chrootctl.runtime.commands import COMMAND_SPECS, CommandSpec, command_requires_root, dispatch_command, maybe_reexec_with_sudo
from chrootctl.runtime.common import ensure_json_supported


class Runner:
    def __init__(self, *, is_root: bool = False) -> None:
        self._is_root = is_root
        self.reexec_calls: list[list[str]] = []

    def is_root(self) -> bool:
        return self._is_root

    def reexec_with_sudo(self, argv: list[str]) -> int:
        self.reexec_calls.append(list(argv))
        return 77

    def python_reexec_argv(self) -> list[str]:
        return ["python", "-m", "chrootctl"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["status"], False),
        (["doctor"], False),
        (["logs"], False),
        (["mount"], True),
        (["unmount"], True),
        (["fix-tty"], True),
        (["start"], True),
        (["restart"], True),
        (["exec"], True),
        (["install", "ubuntu"], True),
        (["upgrade"], True),
        (["users", "list"], True),
        (["chroots", "list"], False),
        (["chroots", "remove"], True),
        (["transfer", "export"], True),
        (["transfer", "import"], True),
        (["tools", "list"], False),
        (["tools", "apply"], True),
        (["addons", "list"], False),
        (["addons", "apply"], True),
    ],
)
def test_command_requires_root_uses_command_metadata(argv: list[str], expected: bool) -> None:
    args = argparse.Namespace(
        command=argv[0],
        chroots_command=argv[1] if argv[0] == "chroots" and len(argv) > 1 else None,
        tools_command=argv[1] if argv[0] == "tools" and len(argv) > 1 else None,
        addons_command=argv[1] if argv[0] == "addons" and len(argv) > 1 else None,
        transfer_command=argv[1] if argv[0] == "transfer" and len(argv) > 1 else None,
    )

    assert command_requires_root(args) is expected


def test_maybe_reexec_with_sudo_skips_non_root_command() -> None:
    runner = Runner(is_root=False)
    args = argparse.Namespace(command="status", no_sudo=False)

    maybe_reexec_with_sudo(args, runner)

    assert runner.reexec_calls == []


def test_maybe_reexec_with_sudo_reexecs_required_command() -> None:
    runner = Runner(is_root=False)
    args = argparse.Namespace(command="mount", no_sudo=False)

    with pytest.raises(SystemExit, match="77"):
        maybe_reexec_with_sudo(args, runner)

    assert runner.reexec_calls == [["python", "-m", "chrootctl"]]


def test_maybe_reexec_with_sudo_respects_no_sudo() -> None:
    runner = Runner(is_root=False)
    args = argparse.Namespace(command="mount", no_sudo=True)

    with pytest.raises(PermissionError, match="root privileges required"):
        maybe_reexec_with_sudo(args, runner)


def test_dispatch_command_rejects_unknown_command() -> None:
    context = argparse.Namespace(args=argparse.Namespace(command="missing"), logger=logging.getLogger("test"))

    with pytest.raises(RuntimeError, match="unsupported command: missing"):
        dispatch_command(context)


def test_maybe_reexec_with_sudo_skips_when_already_root() -> None:
    runner = Runner(is_root=True)
    args = argparse.Namespace(command="mount", no_sudo=False)

    maybe_reexec_with_sudo(args, runner)

    assert runner.reexec_calls == []


def test_dispatch_command_uses_handler_from_command_registry(monkeypatch) -> None:
    called = []

    def fake_handler(context) -> None:
        called.append(context.args.command)

    monkeypatch.setitem(COMMAND_SPECS, "status", CommandSpec("status", fake_handler))
    context = argparse.Namespace(args=argparse.Namespace(command="status"))

    dispatch_command(context)

    assert called == ["status"]


def test_ensure_json_supported_allows_supported_command() -> None:
    ensure_json_supported(argparse.Namespace(command="status", json=True))


def test_ensure_json_supported_rejects_unsupported_command() -> None:
    with pytest.raises(RuntimeError, match="--json is not supported for command: logs"):
        ensure_json_supported(argparse.Namespace(command="logs", json=True))
