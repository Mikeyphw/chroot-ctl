from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .config import ChrootConfig
from .controller import ChrootController
from .installer_factory import build_installer
from .logging_utils import configure_logging
from .registry import ChrootRegistry
from .system import SystemRunner
from .user_sync import UserSyncManager

console = Console()
PRIVILEGED_COMMANDS = {"mount", "fix-tty", "start", "install", "users"}

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chrootctl")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--name", default="ubuntu")
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("status")
    subs.add_parser("mount")
    subs.add_parser("fix-tty")

    start = subs.add_parser("start")
    start.add_argument("--login", action="store_true")
    start.add_argument("--root-login", action="store_true")
    start.add_argument("--exec-command", default=None)
    start.add_argument("argv", nargs=argparse.REMAINDER)

    install = subs.add_parser("install")
    install.add_argument("distro", choices=["ubuntu", "arch", "manjaro"])
    install.add_argument("--phase", choices=["extract", "bootstrap", "desktop", "finalize"], default=None)
    install.add_argument("--force-phase", action="store_true")
    install.add_argument("--auto", action="store_true")
    install.add_argument("--list-versions", action="store_true")
    install.add_argument("--version", default=None)
    install.add_argument("--release", default=None)
    install.add_argument("--username", default="mike")
    install.add_argument("--desktop", choices=["xfce4", "plasma", "none"], default="xfce4")

    chroots = subs.add_parser("chroots")
    chroots_sub = chroots.add_subparsers(dest="chroots_command", required=True)
    chroots_sub.add_parser("list")

    users = subs.add_parser("users")
    users_sub = users.add_subparsers(dest="users_command", required=True)
    show_id = users_sub.add_parser("show-id")
    show_id.add_argument("--username", default=None)
    sync_id = users_sub.add_parser("sync-id")
    sync_id.add_argument("--username", default=None)
    sync_id.add_argument("--no-fix-ownership", action="store_true")

    return parser

def maybe_reexec_with_sudo(args: argparse.Namespace, runner: SystemRunner) -> None:
    if args.command not in PRIVILEGED_COMMANDS:
        return
    if runner.is_root():
        return
    if args.no_sudo:
        raise PermissionError("root privileges required; rerun without --no-sudo to auto-escalate")
    code = runner.reexec_with_sudo(runner.python_reexec_argv())
    raise SystemExit(code)

def progress_call(description: str, fn):
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(description, total=None)
        result = fn()
        progress.update(task, completed=1)
        return result

def render_table(title: str, rows: list[dict[str, str]]) -> None:
    keys = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    table = Table(title=title)
    for key in keys:
        table.add_column(key)
    for row in rows:
        table.add_row(*(str(row.get(key, "")) for key in keys))
    console.print(table)

def result_panel(title: str, data: dict[str, str]) -> None:
    console.print(Panel.fit("\n".join(f"{k}={v}" for k, v in data.items()), title=title, border_style="green"))

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = ChrootConfig.load(args.config).with_overrides(distro_name=args.name)
    logger = configure_logging(config.log_file, verbose=args.verbose)
    runner = SystemRunner(logger=logger, dry_run=args.dry_run)
    registry = ChrootRegistry(config.database_path)
    controller = ChrootController(config, runner, logger)
    user_sync = UserSyncManager(config, runner, logger)

    try:
        maybe_reexec_with_sudo(args, runner)

        if args.command == "status":
            render_table("Mount Status", progress_call("Collecting mount status", controller.status))
            return

        if args.command == "mount":
            result = progress_call("Mounting chroot", controller.mount)
            result_panel("Mount", {"success": str(result.success), "failed": str(result.failed), "skipped": str(result.skipped)})
            return

        if args.command == "fix-tty":
            result = progress_call("Fixing tty/devices", controller.fix_tty)
            result_panel("Fix TTY", {"success": str(result.success), "failed": str(result.failed), "skipped": str(result.skipped)})
            return

        if args.command == "start":
            argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
            code = progress_call(
                "Starting chroot session",
                lambda: controller.start(
                    login=args.login,
                    root_login=args.root_login,
                    exec_command=args.exec_command,
                    command_argv=argv or None,
                ),
            )
            raise SystemExit(code)

        if args.command == "chroots":
            if args.chroots_command == "list":
                render_table("Installed Chroots", registry.list())
                return

        if args.command == "users":
            if args.users_command == "show-id":
                result_panel("User IDs", user_sync.show_id(username=args.username))
                return
            if args.users_command == "sync-id":
                result = progress_call(
                    "Syncing user IDs",
                    lambda: user_sync.sync_id(username=args.username, fix_ownership=not args.no_fix_ownership),
                )
                result_panel("User Sync", result)
                return

        if args.command == "install":
            installer = build_installer(
                args.distro,
                config=config.with_overrides(username=args.username),
                runner=runner,
                controller=ChrootController(config.with_overrides(username=args.username), runner, logger),
                registry=registry,
                user_sync=UserSyncManager(config.with_overrides(username=args.username), runner, logger),
                logger=logger,
            )
            if args.list_versions:
                render_table("Available Versions", [vars(v) for v in progress_call("Fetching versions", installer.list_versions)])
                return
            results = progress_call(
                f"Installing {args.distro}",
                lambda: installer.install(
                    phase=args.phase,
                    username=args.username,
                    desktop=args.desktop,
                    version=args.version,
                    release=args.release,
                    force_phase=args.force_phase,
                    auto=args.auto,
                ),
            )
            render_table("Install Results", results)
            return

    except PermissionError as exc:
        console.print(f"[red]permission error:[/red] {exc}")
        raise SystemExit(2)
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("command failed")
        console.print(f"[red]error:[/red] {exc}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
