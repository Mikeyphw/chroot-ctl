from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from .catalog import ManifestCatalog
from .chroot_users import ChrootUserManager
from .completion import (
    completion_chroot_details,
    completion_chroot_names,
    completion_chroot_preview,
    generate_zsh_completion,
)
from .config import ChrootConfig
from .controller import ChrootController
from .interactive import Choice, select_one
from .installer_factory import build_installer
from .logging_utils import configure_logging
from .registry import ChrootRegistry
from .output import build_console, wrap_text
from .system import SystemRunner
from .user_sync import UserSyncManager

console = build_console()
INSTALL_PROFILES = ["minimal", "dev", "xfce4", "plasma", "custom"]

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chrootctl")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--name", default="ubuntu")
    subs = parser.add_subparsers(dest="command", required=True)

    status = subs.add_parser("status")
    status.add_argument("--verbose", action="store_true")
    subs.add_parser("mount")
    subs.add_parser("unmount")
    subs.add_parser("fix-tty")
    subs.add_parser("doctor")
    logs = subs.add_parser("logs")
    logs.add_argument("--tail", type=int, default=100)
    logs.add_argument("--all", action="store_true")

    start = subs.add_parser("start")
    start.add_argument("--login", action="store_true")
    start.add_argument("--root-login", action="store_true")
    start.add_argument("target", nargs="?")

    restart = subs.add_parser("restart")
    restart.add_argument("--login", action="store_true")
    restart.add_argument("--root-login", action="store_true")
    restart.add_argument("target", nargs="?")

    exec_parser = subs.add_parser("exec")
    exec_parser.add_argument("--root", action="store_true")
    exec_parser.add_argument("--command", dest="exec_text", default=None)
    exec_parser.add_argument("argv", nargs=argparse.REMAINDER)

    install = subs.add_parser("install")
    install.add_argument("distro", choices=["ubuntu", "arch"])
    install.add_argument("--phase", choices=["extract", "bootstrap", "desktop", "finalize"], default=None)
    install.add_argument("--force-phase", action="store_true")
    install.add_argument("--auto", action="store_true", help="Run remaining phases from --phase; default install already auto-advances")
    install.add_argument("--resume", action="store_true")
    install.add_argument("--repair", action="store_true")
    install.add_argument("--list-versions", action="store_true")
    install.add_argument("--version", default=None)
    install.add_argument("--release", default=None)
    install.add_argument("--username", default="mike")
    install.add_argument("--desktop", choices=["xfce4", "plasma", "none"], default=None)
    install.add_argument("--profile", choices=INSTALL_PROFILES, default=None)
    install.add_argument("--tool", dest="tools", action="append", default=[])
    install.add_argument("--addon", dest="addons", action="append", default=[])
    install.add_argument("--select-tools", action="store_true")
    install.add_argument("--select-addons", action="store_true")

    upgrade = subs.add_parser("upgrade")
    upgrade.add_argument("--username", default="mike")

    completion = subs.add_parser("completion")
    completion_sub = completion.add_subparsers(dest="completion_shell", required=True)
    completion_sub.add_parser("zsh")

    chroots = subs.add_parser("chroots")
    chroots_sub = chroots.add_subparsers(dest="chroots_command", required=True)
    chroots_sub.add_parser("list")
    show = chroots_sub.add_parser("show")
    show.add_argument("chroot_name", nargs="?")
    remove = chroots_sub.add_parser("remove")
    remove.add_argument("chroot_name", nargs="?")
    rename = chroots_sub.add_parser("rename")
    rename.add_argument("old_name", nargs="?")
    rename.add_argument("new_name", nargs="?")

    users = subs.add_parser("users")
    users_sub = users.add_subparsers(dest="users_command", required=True)
    users_list = users_sub.add_parser("list")
    users_list.add_argument("--name", default=argparse.SUPPRESS)
    users_show = users_sub.add_parser("show")
    users_show.add_argument("username", nargs="?")
    users_show.add_argument("--name", default=argparse.SUPPRESS)
    users_add = users_sub.add_parser("add")
    users_add.add_argument("username", nargs="?")
    users_add.add_argument("--shell", default="/bin/bash")
    users_add.add_argument("--sudo", action="store_true")
    users_add.add_argument("--name", default=argparse.SUPPRESS)
    users_remove = users_sub.add_parser("remove")
    users_remove.add_argument("username", nargs="?")
    users_remove.add_argument("--delete-home", action="store_true")
    users_remove.add_argument("--name", default=argparse.SUPPRESS)
    users_password = users_sub.add_parser("password")
    users_password.add_argument("username", nargs="?")
    users_password.add_argument("--name", default=argparse.SUPPRESS)
    users_shell = users_sub.add_parser("shell")
    users_shell.add_argument("username", nargs="?")
    users_shell.add_argument("--shell", required=True)
    users_shell.add_argument("--name", default=argparse.SUPPRESS)
    users_sudo = users_sub.add_parser("sudo")
    users_sudo.add_argument("username", nargs="?")
    sudo_mode = users_sudo.add_mutually_exclusive_group(required=True)
    sudo_mode.add_argument("--enable", action="store_true")
    sudo_mode.add_argument("--disable", action="store_true")
    users_sudo.add_argument("--name", default=argparse.SUPPRESS)
    show_id = users_sub.add_parser("show-id")
    show_id.add_argument("--username", default=None)
    show_id.add_argument("--name", default=argparse.SUPPRESS)
    sync_id = users_sub.add_parser("sync-id")
    sync_id.add_argument("--username", default=None)
    sync_id.add_argument("--no-fix-ownership", action="store_true")
    sync_id.add_argument("--name", default=argparse.SUPPRESS)


    tools = subs.add_parser("tools")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    tools_categories = tools_sub.add_parser("categories")
    tools_categories.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    tools_list = tools_sub.add_parser("list")
    tools_list.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    tools_list.add_argument("--category", default=None)
    tools_show = tools_sub.add_parser("show")
    tools_show.add_argument("tool_name", nargs="?")
    tools_apply = tools_sub.add_parser("apply")
    tools_apply.add_argument("tool_names", nargs="*")
    tools_apply.add_argument("--name", default=argparse.SUPPRESS)
    tools_select = tools_sub.add_parser("select")
    tools_select.add_argument("--category", default=None)
    tools_select.add_argument("--name", default=argparse.SUPPRESS)

    addons = subs.add_parser("addons")
    addons_sub = addons.add_subparsers(dest="addons_command", required=True)
    addons_categories = addons_sub.add_parser("categories")
    addons_categories.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    addons_list = addons_sub.add_parser("list")
    addons_list.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    addons_list.add_argument("--category", default=None)
    addons_show = addons_sub.add_parser("show")
    addons_show.add_argument("addon_name", nargs="?")
    addons_apply = addons_sub.add_parser("apply")
    addons_apply.add_argument("addon_names", nargs="*")
    addons_apply.add_argument("--name", default=argparse.SUPPRESS)
    addons_select = addons_sub.add_parser("select")
    addons_select.add_argument("--category", default=None)
    addons_select.add_argument("--name", default=argparse.SUPPRESS)

    hidden = subs.add_parser("__complete")
    hidden.add_argument("topic", choices=["chroots", "chroot-details", "chroot-preview", "users", "tools", "addons"])
    hidden.add_argument("value", nargs="?")

    return parser

def command_requires_root(args: argparse.Namespace) -> bool:
    if args.command in {"mount", "unmount", "fix-tty", "start", "restart", "exec", "install", "upgrade", "users"}:
        return True
    if args.command == "chroots" and args.chroots_command == "remove":
        return True
    if args.command == "tools" and args.tools_command in {"apply", "select"}:
        return True
    if args.command == "addons" and args.addons_command in {"apply", "select"}:
        return True
    return False

def maybe_reexec_with_sudo(args: argparse.Namespace, runner: SystemRunner) -> None:
    if not command_requires_root(args):
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
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    if not keys:
        console.print(Panel(title, expand=False))
        return

    table = Table(title=title, box=None, expand=True, pad_edge=False, show_header=True)
    for index, key in enumerate(keys):
        table.add_column(
            key,
            overflow="fold",
            no_wrap=False,
            ratio=1 if index == 0 else 3,
        )
    for row in rows:
        table.add_row(*(str(row.get(key, "")) for key in keys))
    console.print(table)

def result_panel(title: str, data: dict[str, str]) -> None:
    body = Table.grid(expand=True)
    body.add_column(style="bold cyan", no_wrap=True)
    body.add_column(overflow="fold", ratio=1)
    for key, value in data.items():
        body.add_row(f"{key}=", str(value))
    console.print(Panel(body, title=title, expand=False))

def flatten_record(record: dict[str, object]) -> dict[str, str]:
    data = {key: str(value) for key, value in record.items() if key != "metadata_json"}
    metadata = record.get("metadata", {})
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            data[f"metadata.{key}"] = str(value)
    return data

def read_logs(log_file: Path, *, tail: int, show_all: bool) -> str:
    if not log_file.exists():
        return ""
    lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    if show_all:
        return "\n".join(lines)
    return "\n".join(lines[-tail:])

def mount_summary(config: ChrootConfig) -> str:
    mounts = list(config.media_mounts) + list(config.extra_bind_mounts)
    if not mounts:
        return "none"
    return ", ".join(
        f"{mount.source}->{mount.target}{':ro' if mount.read_only else ''}"
        for mount in mounts
        if mount.enabled
    )

def remove_chroot(config: ChrootConfig, registry: ChrootRegistry, runner: SystemRunner, logger, name: str) -> dict[str, str]:
    record = registry.get(name)
    target_config = config.for_chroot(name)
    controller = ChrootController(target_config, runner, logger)
    unmount_result = controller.unmount()
    target_path = Path(record["path"]) if record else target_config.chroot_base
    resolved_root = target_config.chroot_root.resolve()
    resolved_target = target_path.resolve(strict=False)
    if resolved_root not in resolved_target.parents and resolved_root != resolved_target:
        raise RuntimeError(f"refusing to delete path outside chroot root: {resolved_target}")
    if target_path.exists() and not runner.dry_run:
        shutil.rmtree(target_path)
    registry.delete(name)
    return {
        "name": name,
        "removed": "yes",
        "unmounted_success": str(unmount_result.success),
        "unmounted_failed": str(unmount_result.failed),
    }

def rename_chroot(config: ChrootConfig, registry: ChrootRegistry, old_name: str, new_name: str) -> dict[str, str]:
    old_config = config.for_chroot(old_name)
    new_config = config.for_chroot(new_name)
    if old_config.chroot_base.exists() and not new_config.chroot_base.exists():
        old_config.chroot_base.rename(new_config.chroot_base)
    registry.rename(old_name, new_name, new_path=str(new_config.chroot_base))
    return {"old_name": old_name, "new_name": new_name, "renamed": "yes"}



def render_catalog_table(title: str, entries) -> None:
    rows = [
        {
            "name": entry.name,
            "description": entry.description,
            "distros": ",".join(entry.distros),
            "categories": ",".join(entry.categories),
            "script": entry.script,
        }
        for entry in entries
    ]
    render_table(title, rows)


def render_category_table(title: str, categories: list[str]) -> None:
    render_table(title, [{"category": category} for category in categories])


def catalog_result_panel(kind: str, entry) -> None:
    result_panel(
        kind.title(),
        {
            "name": entry.name,
            "description": entry.description,
            "distros": ",".join(entry.distros),
            "categories": ",".join(entry.categories),
            "script": entry.script,
        },
    )


def apply_catalog_entries(*, catalog: ManifestCatalog, names: list[str], config: ChrootConfig, runner: SystemRunner, registry: ChrootRegistry, logger) -> list[dict[str, str]]:
    return [
        catalog.apply(name=name, config=config, runner=runner, registry=registry, logger=logger)
        for name in names
    ]


def install_selection_names(*, catalog: ManifestCatalog, distro: str, explicit_names: list[str], select_flag: bool) -> list[str]:
    names = list(dict.fromkeys(explicit_names))
    if select_flag:
        chosen = catalog.select_names(distro=distro, prompt=f"Select {catalog.kind}s")
        for name in chosen:
            if name not in names:
                names.append(name)
    return names

def select_chroot_name(registry: ChrootRegistry, *, prompt: str, installed_only: bool = False) -> str:
    records = [
        record
        for record in registry.list()
        if not installed_only or bool(record.get("installed"))
    ]
    choices = [
        Choice(
            value=str(record["name"]),
            label=str(record["name"]),
            description=f"{record.get('distro', '')} {record.get('phase', '')}",
        )
        for record in records
    ]
    return select_one(choices, prompt=prompt)

def resolve_chroot_arg(
    value: str | None,
    registry: ChrootRegistry,
    *,
    prompt: str,
    installed_only: bool = False,
) -> str:
    return value or select_chroot_name(registry, prompt=prompt, installed_only=installed_only)

def select_chroot_username(manager: ChrootUserManager, *, prompt: str) -> str:
    choices = [
        Choice(
            value=user.username,
            label=user.username,
            description=f"uid={user.uid} shell={user.shell}",
        )
        for user in manager.list_users()
    ]
    return select_one(choices, prompt=prompt)

def resolve_username_arg(value: str | None, manager: ChrootUserManager, *, prompt: str) -> str:
    return value or select_chroot_username(manager, prompt=prompt)

def select_catalog_name(catalog: ManifestCatalog, *, distro: str | None, category: str | None, prompt: str) -> str:
    entries = catalog.list_entries(distro=distro, category=category)
    choices = [
        Choice(
            value=entry.name,
            label=entry.name,
            description=f"{','.join(entry.categories) or 'uncategorized'} - {entry.description}",
        )
        for entry in entries
    ]
    return select_one(choices, prompt=prompt)

def select_catalog_names(catalog: ManifestCatalog, *, distro: str, category: str | None, prompt: str) -> list[str]:
    return catalog.select_names(distro=distro, prompt=prompt, category=category)

def registry_distro_for_config(registry: ChrootRegistry, config: ChrootConfig) -> str:
    record = registry.get(config.distro_name)
    if record is None:
        raise RuntimeError("chroot must be installed first")
    return str(record.get("distro", ""))

def completion_user_names(config: ChrootConfig) -> str:
    passwd_path = config.chroot_base / "etc" / "passwd"
    if not passwd_path.exists():
        return ""
    names: list[str] = []
    for line in passwd_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split(":")
        if len(parts) >= 7 and parts[0]:
            names.append(parts[0])
    return "\n".join(sorted(names))

def completion_catalog_names(kind: str, distro: str | None = None) -> str:
    catalog = ManifestCatalog("tool" if kind == "tools" else "addon")
    return "\n".join(entry.name for entry in catalog.list_entries(distro=distro))

def apply_start_name_shorthand(
    args: argparse.Namespace,
    config: ChrootConfig,
    registry: ChrootRegistry,
) -> ChrootConfig:
    if args.command not in {"start", "restart"}:
        return config
    target = getattr(args, "target", None)
    if not target:
        return config
    record = registry.get(target)
    if record is None:
        return config
    args.target = None
    return config.for_chroot(str(record["name"]))

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = ChrootConfig.load(args.config).for_chroot(args.name)
    if args.command == "completion":
        if args.completion_shell == "zsh":
            sys.stdout.write(generate_zsh_completion(parser.prog))
            return
    if args.command == "__complete":
        registry = ChrootRegistry(config.database_path)
        if args.topic == "chroots":
            sys.stdout.write(completion_chroot_names(registry.list()))
            return
        if args.topic == "chroot-details":
            sys.stdout.write(completion_chroot_details(registry.list()))
            return
        if args.topic == "chroot-preview":
            record = registry.get(args.value or "")
            sys.stdout.write(completion_chroot_preview(record))
            return
        if args.topic == "users":
            target = config.for_chroot(args.value or config.distro_name)
            sys.stdout.write(completion_user_names(target))
            return
        if args.topic in {"tools", "addons"}:
            sys.stdout.write(completion_catalog_names(args.topic, args.value))
            return

    logger = configure_logging(config.log_file, verbose=args.verbose)
    runner = SystemRunner(logger=logger, dry_run=args.dry_run)
    registry = ChrootRegistry(config.database_path)
    config = apply_start_name_shorthand(args, config, registry)
    controller = ChrootController(config, runner, logger)
    user_sync = UserSyncManager(config, runner, logger)
    chroot_users = ChrootUserManager(config, runner, registry, logger)

    try:
        maybe_reexec_with_sudo(args, runner)

        if args.command == "status":
            rows = progress_call("Collecting mount status", lambda: controller.status(verbose=args.verbose))
            render_table("Mount Status", rows)
            if args.verbose:
                record = registry.get(config.distro_name)
                if record:
                    result_panel("Chroot", {"name": config.distro_name, "phase": str(record.get("phase", "")), "installed": str(record.get("installed", ""))})
            return

        if args.command == "mount":
            result = progress_call("Mounting chroot", controller.mount)
            result_panel("Mount", {"success": str(result.success), "failed": str(result.failed), "skipped": str(result.skipped)})
            return

        if args.command == "unmount":
            result = progress_call("Unmounting chroot", controller.unmount)
            result_panel("Unmount", {"success": str(result.success), "failed": str(result.failed), "skipped": str(result.skipped)})
            return

        if args.command == "fix-tty":
            result = progress_call("Fixing tty/devices", controller.fix_tty)
            result_panel("Fix TTY", {"success": str(result.success), "failed": str(result.failed), "skipped": str(result.skipped)})
            return

        if args.command == "doctor":
            rows = progress_call("Running diagnostics", controller.doctor)
            record = registry.get(config.distro_name)
            if record:
                rows.append({"check": "registry", "status": "ok", "detail": f"phase={record.get('phase')} installed={record.get('installed')}"})
            rows.append({"check": "log_file", "status": "ok" if config.log_file.exists() else "warning", "detail": str(config.log_file)})
            render_table("Doctor", rows)
            return

        if args.command == "logs":
            text = read_logs(config.log_file, tail=args.tail, show_all=args.all)
            console.print(Panel(Text(text or "no logs available", overflow="fold"), title="Logs", expand=True))
            return

        if args.command == "start":
            code = progress_call(
                "Starting chroot session",
                lambda: controller.start(
                    login=args.login,
                    root_login=args.root_login,
                ),
            )
            raise SystemExit(code)

        if args.command == "restart":
            code = progress_call(
                "Restarting chroot session",
                lambda: controller.restart(
                    login=args.login,
                    root_login=args.root_login,
                ),
            )
            raise SystemExit(code)

        if args.command == "exec":
            argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
            code = progress_call(
                "Executing command in chroot",
                lambda: controller.exec(root=args.root, argv=argv or None, command=args.exec_text),
            )
            raise SystemExit(code)

        if args.command == "chroots":
            if args.chroots_command == "list":
                render_table("Installed Chroots", registry.list())
                return
            if args.chroots_command == "show":
                chroot_name = resolve_chroot_arg(args.chroot_name, registry, prompt="Select chroot")
                record = registry.get(chroot_name)
                if record is None:
                    raise RuntimeError(f"unknown chroot: {chroot_name}")
                target_config = config.for_chroot(chroot_name)
                data = flatten_record(record)
                data["configured_mounts"] = mount_summary(target_config)
                data["extra_packages"] = ",".join(target_config.extra_packages) or "none"
                data["locale"] = target_config.locale
                result_panel("Chroot Details", data)
                return
            if args.chroots_command == "remove":
                chroot_name = resolve_chroot_arg(args.chroot_name, registry, prompt="Select chroot to remove")
                result = progress_call(
                    "Removing chroot",
                    lambda: remove_chroot(config, registry, runner, logger, chroot_name),
                )
                result_panel("Chroot Remove", result)
                return
            if args.chroots_command == "rename":
                old_name = resolve_chroot_arg(args.old_name, registry, prompt="Select chroot to rename")
                if not args.new_name:
                    raise RuntimeError("new chroot name is required")
                result = progress_call(
                    "Renaming chroot",
                    lambda: rename_chroot(config, registry, old_name, args.new_name),
                )
                result_panel("Chroot Rename", result)
                return

        if args.command == "users":
            user_manager = chroot_users
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
            if args.users_command == "list":
                render_table("Chroot Users", user_manager.user_rows())
                return
            if args.users_command == "show":
                username = resolve_username_arg(args.username, user_manager, prompt="Select user")
                result_panel("Chroot User", user_manager.show_user(username))
                return
            if args.users_command == "add":
                if not args.username:
                    raise RuntimeError("username is required")
                result = progress_call(
                    "Adding chroot user",
                    lambda: user_manager.add_user(args.username, shell=args.shell, sudo=args.sudo),
                )
                result_panel("Chroot User Add", result)
                return
            if args.users_command == "remove":
                username = resolve_username_arg(args.username, user_manager, prompt="Select user to remove")
                result = progress_call(
                    "Removing chroot user",
                    lambda: user_manager.remove_user(username, delete_home=args.delete_home),
                )
                result_panel("Chroot User Remove", result)
                return
            if args.users_command == "password":
                username = resolve_username_arg(args.username, user_manager, prompt="Select user for password")
                result = progress_call(
                    "Updating chroot user password",
                    lambda: user_manager.set_password(username),
                )
                result_panel("Chroot User Password", result)
                return
            if args.users_command == "shell":
                username = resolve_username_arg(args.username, user_manager, prompt="Select user for shell")
                result = progress_call(
                    "Updating chroot user shell",
                    lambda: user_manager.set_shell(username, shell=args.shell),
                )
                result_panel("Chroot User Shell", result)
                return
            if args.users_command == "sudo":
                username = resolve_username_arg(args.username, user_manager, prompt="Select user for sudo")
                result = progress_call(
                    "Updating chroot user sudo",
                    lambda: user_manager.set_sudo(username, enabled=args.enable),
                )
                result_panel("Chroot User Sudo", result)
                return

        if args.command == "tools":
            catalog = ManifestCatalog("tool", config=config)
            if args.tools_command == "categories":
                render_category_table("Tool Categories", catalog.categories(distro=args.distro))
                return
            if args.tools_command == "list":
                render_catalog_table("Tools", catalog.list_entries(distro=args.distro, category=args.category))
                return
            if args.tools_command == "show":
                tool_name = args.tool_name or select_catalog_name(catalog, distro=None, category=None, prompt="Select tool")
                catalog_result_panel("tool", catalog.get_entry(tool_name))
                return
            if args.tools_command == "apply":
                tool_names = args.tool_names or select_catalog_names(
                    catalog,
                    distro=registry_distro_for_config(registry, config),
                    category=None,
                    prompt="Select tools",
                )
                results = progress_call(
                    "Applying tools",
                    lambda: apply_catalog_entries(
                        catalog=catalog,
                        names=tool_names,
                        config=config,
                        runner=runner,
                        registry=registry,
                        logger=logger,
                    ),
                )
                render_table("Tools", results)
                return
            if args.tools_command == "select":
                names = select_catalog_names(
                    catalog,
                    distro=registry_distro_for_config(registry, config),
                    category=args.category,
                    prompt="Select tools",
                )
                results = progress_call(
                    "Applying tools",
                    lambda: apply_catalog_entries(
                        catalog=catalog,
                        names=names,
                        config=config,
                        runner=runner,
                        registry=registry,
                        logger=logger,
                    ),
                )
                render_table("Tools", results)
                return

        if args.command == "addons":
            catalog = ManifestCatalog("addon", config=config)
            if args.addons_command == "categories":
                render_category_table("Addon Categories", catalog.categories(distro=args.distro))
                return
            if args.addons_command == "list":
                render_catalog_table("Addons", catalog.list_entries(distro=args.distro, category=args.category))
                return
            if args.addons_command == "show":
                addon_name = args.addon_name or select_catalog_name(catalog, distro=None, category=None, prompt="Select addon")
                catalog_result_panel("addon", catalog.get_entry(addon_name))
                return
            if args.addons_command == "apply":
                addon_names = args.addon_names or select_catalog_names(
                    catalog,
                    distro=registry_distro_for_config(registry, config),
                    category=None,
                    prompt="Select addons",
                )
                results = progress_call(
                    "Applying addons",
                    lambda: apply_catalog_entries(
                        catalog=catalog,
                        names=addon_names,
                        config=config,
                        runner=runner,
                        registry=registry,
                        logger=logger,
                    ),
                )
                render_table("Addons", results)
                return
            if args.addons_command == "select":
                names = select_catalog_names(
                    catalog,
                    distro=registry_distro_for_config(registry, config),
                    category=args.category,
                    prompt="Select addons",
                )
                results = progress_call(
                    "Applying addons",
                    lambda: apply_catalog_entries(
                        catalog=catalog,
                        names=names,
                        config=config,
                        runner=runner,
                        registry=registry,
                        logger=logger,
                    ),
                )
                render_table("Addons", results)
                return

        if args.command == "install":
            install_config = config.with_overrides(username=args.username)
            installer = build_installer(
                args.distro,
                config=install_config,
                runner=runner,
                controller=ChrootController(install_config, runner, logger),
                registry=registry,
                user_sync=UserSyncManager(install_config, runner, logger),
                logger=logger,
            )
            if args.list_versions:
                render_table("Available Versions", [vars(v) for v in progress_call("Fetching versions", installer.list_versions)])
                return
            selected_tools = install_selection_names(
                catalog=ManifestCatalog("tool", config=config),
                distro=args.distro,
                explicit_names=args.tools,
                select_flag=args.select_tools,
            )
            selected_addons = install_selection_names(
                catalog=ManifestCatalog("addon", config=config),
                distro=args.distro,
                explicit_names=args.addons,
                select_flag=args.select_addons,
            )
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
                    resume=args.resume,
                    repair=args.repair,
                    profile=args.profile,
                ),
            )
            if selected_tools or selected_addons:
                record = registry.get(install_config.distro_name)
                if record is None or not bool(record.get("installed")):
                    raise RuntimeError("tools and addons can only be applied after finalize completes")
                if selected_tools:
                    tool_results = progress_call(
                        "Applying tools",
                        lambda: apply_catalog_entries(
                            catalog=ManifestCatalog("tool", config=config),
                            names=selected_tools,
                            config=install_config,
                            runner=runner,
                            registry=registry,
                            logger=logger,
                        ),
                    )
                    results.extend(tool_results)
                if selected_addons:
                    addon_results = progress_call(
                        "Applying addons",
                        lambda: apply_catalog_entries(
                            catalog=ManifestCatalog("addon", config=config),
                            names=selected_addons,
                            config=install_config,
                            runner=runner,
                            registry=registry,
                            logger=logger,
                        ),
                    )
                    results.extend(addon_results)
            render_table("Install Results", results)
            return

        if args.command == "upgrade":
            record = registry.get(config.distro_name)
            if record is None:
                raise RuntimeError(f"no registry record for chroot: {config.distro_name}")
            upgrade_config = config.with_overrides(username=args.username)
            installer = build_installer(
                str(record["distro"]),
                config=upgrade_config,
                runner=runner,
                controller=ChrootController(upgrade_config, runner, logger),
                registry=registry,
                user_sync=UserSyncManager(upgrade_config, runner, logger),
                logger=logger,
            )
            result = progress_call("Upgrading chroot", installer.upgrade)
            result_panel("Upgrade", result)
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
