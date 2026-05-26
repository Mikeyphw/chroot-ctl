from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .catalog import ManifestCatalog
from .completion import (
    completion_chroot_details,
    completion_chroot_names,
    completion_chroot_preview,
    generate_zsh_completion,
)
from .config import ChrootConfig
from .controller import ChrootController
from .installer_factory import build_installer
from .logging_utils import configure_logging
from .registry import ChrootRegistry
from .system import SystemRunner
from .user_sync import UserSyncManager

console = Console()
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
    start.add_argument("--exec-command", default=None)
    start.add_argument("argv", nargs=argparse.REMAINDER)

    restart = subs.add_parser("restart")
    restart.add_argument("--login", action="store_true")
    restart.add_argument("--root-login", action="store_true")
    restart.add_argument("--exec-command", default=None)
    restart.add_argument("argv", nargs=argparse.REMAINDER)

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
    show.add_argument("chroot_name")
    remove = chroots_sub.add_parser("remove")
    remove.add_argument("chroot_name")
    rename = chroots_sub.add_parser("rename")
    rename.add_argument("old_name")
    rename.add_argument("new_name")

    users = subs.add_parser("users")
    users_sub = users.add_subparsers(dest="users_command", required=True)
    show_id = users_sub.add_parser("show-id")
    show_id.add_argument("--username", default=None)
    sync_id = users_sub.add_parser("sync-id")
    sync_id.add_argument("--username", default=None)
    sync_id.add_argument("--no-fix-ownership", action="store_true")


    tools = subs.add_parser("tools")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    tools_categories = tools_sub.add_parser("categories")
    tools_categories.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    tools_list = tools_sub.add_parser("list")
    tools_list.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    tools_list.add_argument("--category", default=None)
    tools_show = tools_sub.add_parser("show")
    tools_show.add_argument("tool_name")
    tools_apply = tools_sub.add_parser("apply")
    tools_apply.add_argument("tool_names", nargs="+")
    tools_select = tools_sub.add_parser("select")
    tools_select.add_argument("--category", default=None)

    addons = subs.add_parser("addons")
    addons_sub = addons.add_subparsers(dest="addons_command", required=True)
    addons_categories = addons_sub.add_parser("categories")
    addons_categories.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    addons_list = addons_sub.add_parser("list")
    addons_list.add_argument("--distro", choices=["ubuntu", "arch"], default=None)
    addons_list.add_argument("--category", default=None)
    addons_show = addons_sub.add_parser("show")
    addons_show.add_argument("addon_name")
    addons_apply = addons_sub.add_parser("apply")
    addons_apply.add_argument("addon_names", nargs="+")
    addons_select = addons_sub.add_parser("select")
    addons_select.add_argument("--category", default=None)

    hidden = subs.add_parser("__complete")
    hidden.add_argument("topic", choices=["chroots", "chroot-details", "chroot-preview"])
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

    logger = configure_logging(config.log_file, verbose=args.verbose)
    runner = SystemRunner(logger=logger, dry_run=args.dry_run)
    registry = ChrootRegistry(config.database_path)
    controller = ChrootController(config, runner, logger)
    user_sync = UserSyncManager(config, runner, logger)

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
            console.print(Panel.fit(text or "no logs available", title="Logs"))
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

        if args.command == "restart":
            argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
            code = progress_call(
                "Restarting chroot session",
                lambda: controller.restart(
                    login=args.login,
                    root_login=args.root_login,
                    exec_command=args.exec_command,
                    command_argv=argv or None,
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
                record = registry.get(args.chroot_name)
                if record is None:
                    raise RuntimeError(f"unknown chroot: {args.chroot_name}")
                target_config = config.for_chroot(args.chroot_name)
                data = flatten_record(record)
                data["configured_mounts"] = mount_summary(target_config)
                data["extra_packages"] = ",".join(target_config.extra_packages) or "none"
                data["locale"] = target_config.locale
                result_panel("Chroot Details", data)
                return
            if args.chroots_command == "remove":
                result = progress_call(
                    "Removing chroot",
                    lambda: remove_chroot(config, registry, runner, logger, args.chroot_name),
                )
                result_panel("Chroot Remove", result)
                return
            if args.chroots_command == "rename":
                result = progress_call(
                    "Renaming chroot",
                    lambda: rename_chroot(config, registry, args.old_name, args.new_name),
                )
                result_panel("Chroot Rename", result)
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

        if args.command == "tools":
            catalog = ManifestCatalog("tool", config=config)
            if args.tools_command == "categories":
                render_category_table("Tool Categories", catalog.categories(distro=args.distro))
                return
            if args.tools_command == "list":
                render_catalog_table("Tools", catalog.list_entries(distro=args.distro, category=args.category))
                return
            if args.tools_command == "show":
                catalog_result_panel("tool", catalog.get_entry(args.tool_name))
                return
            if args.tools_command == "apply":
                results = progress_call(
                    "Applying tools",
                    lambda: apply_catalog_entries(
                        catalog=catalog,
                        names=args.tool_names,
                        config=config,
                        runner=runner,
                        registry=registry,
                        logger=logger,
                    ),
                )
                render_table("Tools", results)
                return
            if args.tools_command == "select":
                names = catalog.select_names(distro=(registry.get(config.distro_name) or {}).get("distro", "ubuntu"), prompt="Select tools", category=args.category)
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
                catalog_result_panel("addon", catalog.get_entry(args.addon_name))
                return
            if args.addons_command == "apply":
                results = progress_call(
                    "Applying addons",
                    lambda: apply_catalog_entries(
                        catalog=catalog,
                        names=args.addon_names,
                        config=config,
                        runner=runner,
                        registry=registry,
                        logger=logger,
                    ),
                )
                render_table("Addons", results)
                return
            if args.addons_command == "select":
                names = catalog.select_names(distro=(registry.get(config.distro_name) or {}).get("distro", "ubuntu"), prompt="Select addons", category=args.category)
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
