from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..system import SystemRunner
from .catalog import handle_addons, handle_tools
from .clipboard import handle_clipboard
from .chroots import handle_chroots
from .install import handle_install, handle_upgrade
from .magisk import handle_magisk
from .session import (
    handle_doctor,
    handle_exec,
    handle_fix_tty,
    handle_logs,
    handle_mount,
    handle_restart,
    handle_start,
    handle_status,
    handle_unmount,
)
from .transfer import handle_transfer
from .units import handle_disable, handle_enable, handle_journal, handle_run
from .users import handle_users
from .common import emit_panel, emit_table, progress_call

if TYPE_CHECKING:
    from .core import RuntimeContext


CommandHandler = Callable[[Any], None]


@dataclass(frozen=True, slots=True)
class RootPolicy:
    always: bool = False
    subcommand_attr: str | None = None
    subcommands: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def always_required(cls) -> "RootPolicy":
        return cls(always=True)

    @classmethod
    def for_subcommands(cls, subcommand_attr: str, *subcommands: str) -> "RootPolicy":
        return cls(subcommand_attr=subcommand_attr, subcommands=frozenset(subcommands))

    def requires_root(self, args: argparse.Namespace) -> bool:
        if self.always:
            return True
        if self.subcommand_attr is None:
            return False
        return getattr(args, self.subcommand_attr, None) in self.subcommands


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    handler: CommandHandler
    root_policy: RootPolicy = field(default_factory=RootPolicy)


COMMAND_SPECS: dict[str, CommandSpec] = {
    "status": CommandSpec("status", handle_status),
    "mount": CommandSpec("mount", handle_mount, RootPolicy.always_required()),
    "unmount": CommandSpec("unmount", handle_unmount, RootPolicy.always_required()),
    "fix-tty": CommandSpec("fix-tty", handle_fix_tty, RootPolicy.always_required()),
    "doctor": CommandSpec("doctor", handle_doctor),
    "logs": CommandSpec("logs", handle_logs),
    "start": CommandSpec("start", handle_start, RootPolicy.always_required()),
    "restart": CommandSpec("restart", handle_restart, RootPolicy.always_required()),
    "exec": CommandSpec("exec", handle_exec, RootPolicy.always_required()),
    "run": CommandSpec("run", handle_run, RootPolicy.always_required()),
    "enable": CommandSpec("enable", handle_enable, RootPolicy.always_required()),
    "disable": CommandSpec("disable", handle_disable, RootPolicy.always_required()),
    "journal": CommandSpec("journal", handle_journal),
    "chroots": CommandSpec("chroots", handle_chroots, RootPolicy.for_subcommands("chroots_command", "remove", "export", "import")),
    "transfer": CommandSpec("transfer", handle_transfer, RootPolicy.for_subcommands("transfer_command", "export", "import")),
    "users": CommandSpec("users", handle_users, RootPolicy.always_required()),
    "tools": CommandSpec("tools", handle_tools, RootPolicy.for_subcommands("tools_command", "apply")),
    "addons": CommandSpec("addons", handle_addons, RootPolicy.for_subcommands("addons_command", "apply")),
    "install": CommandSpec("install", handle_install, RootPolicy.always_required()),
    "upgrade": CommandSpec("upgrade", handle_upgrade, RootPolicy.always_required()),
    "magisk": CommandSpec("magisk", handle_magisk),
    "clipboard": CommandSpec("clipboard", handle_clipboard),
    "events": CommandSpec("events", lambda context: handle_events(context)),
    "support-bundle": CommandSpec("support-bundle", lambda context: handle_support_bundle(context)),
}


def get_command_spec(command_name: str) -> CommandSpec:
    spec = COMMAND_SPECS.get(command_name)
    if spec is None:
        raise RuntimeError(f"unsupported command: {command_name}")
    return spec


def dispatch_command(context: RuntimeContext) -> None:
    get_command_spec(context.args.command).handler(context)


def command_requires_root(args: argparse.Namespace) -> bool:
    return get_command_spec(args.command).root_policy.requires_root(args)


def maybe_reexec_with_sudo(args: argparse.Namespace, runner: SystemRunner) -> None:
    if not command_requires_root(args):
        return
    if runner.is_root():
        return
    if args.no_sudo:
        raise PermissionError("root privileges required; rerun without --no-sudo to auto-escalate")
    code = runner.reexec_with_sudo(runner.python_reexec_argv())
    raise SystemExit(code)


def handle_events(context: "RuntimeContext") -> None:
    args = context.args
    if args.events_command == "list":
        emit_table(context, "Audit Events", context.services.audit().recent(limit=args.limit))
        return
    raise RuntimeError(f"unsupported events command: {args.events_command}")


def handle_support_bundle(context: "RuntimeContext") -> None:
    args = context.args
    result = progress_call(
        "Exporting support bundle",
        lambda: context.services.support().export_bundle(args.archive, jobs=getattr(context, "jobs", None)),
    )
    emit_panel(context, "Support Bundle", result)
