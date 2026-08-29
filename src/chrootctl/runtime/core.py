from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from ..chroot_users import ChrootUserManager
from ..completion import (
    completion_chroot_details,
    completion_chroot_names,
    completion_chroot_preview,
    completion_installed_chroot_names,
    generate_zsh_completion,
)
from ..config import ChrootConfig
from ..controller import ChrootController
from ..logging_utils import configure_logging
from ..output import result_panel
from ..registry import ChrootRegistry
from ..services import create_service_container
from ..system import SystemRunner
from ..user_sync import UserSyncManager
from .catalog import (
    completion_catalog_categories,
    completion_catalog_details,
    completion_catalog_names,
    completion_catalog_preview,
)
from .commands import dispatch_command, maybe_reexec_with_sudo
from .common import console, ensure_json_supported
from .resolution import resolve_runtime_chroot_name
from .users import completion_user_names


@dataclass(slots=True)
class RuntimeContext:
    args: argparse.Namespace
    config: ChrootConfig
    logger: Any
    runner: SystemRunner
    registry: ChrootRegistry
    controller: ChrootController
    user_sync: UserSyncManager
    chroot_users: ChrootUserManager
    services: Any


def execute_cli(
    args: argparse.Namespace,
    *,
    prog: str,
    apply_start_name_shorthand_fn,
) -> None:
    # Static shell completion must not touch Android state, SQLite, root-only
    # paths, or service construction.  This keeps `completion zsh` usable from
    # an ordinary Termux shell and makes the command a true pure-output path.
    if args.command == "completion" and args.completion_shell == "zsh":
        sys.stdout.write(generate_zsh_completion(prog))
        return

    base_config = ChrootConfig.load(args.config)
    registry = ChrootRegistry(base_config.database_path)
    if _handle_completion_command(args, base_config, registry, prog):
        return

    services = create_service_container(args.config, dry_run=args.dry_run, verbose=args.verbose)
    base_config = services.base_config
    registry = services.registry
    resolved_name = resolve_runtime_chroot_name(args, base_config, registry)
    if resolved_name is not None:
        args.name = resolved_name
        config = base_config.for_chroot(resolved_name)
    else:
        config = base_config
    ensure_json_supported(args)
    logger = services.logger
    runner = SystemRunner(logger=logger, dry_run=args.dry_run)
    config = apply_start_name_shorthand_fn(args, config, registry)
    context = RuntimeContext(
        args=args,
        config=config,
        logger=logger,
        runner=runner,
        registry=registry,
        controller=ChrootController(config, runner, logger),
        user_sync=UserSyncManager(config, runner, logger, registry),
        chroot_users=ChrootUserManager(config, runner, registry, logger),
        services=services,
    )

    try:
        maybe_reexec_with_sudo(args, runner)
        dispatch_command(context)
    except PermissionError as exc:
        console.print(f"[red]permission error:[/red] {exc}")
        raise SystemExit(2) from exc
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("command failed")
        result_panel(
            "Failure",
            {
                "error": str(exc),
                "log_file": config.log_file,
                "recovery": _recovery_command(args),
            },
        )
        raise SystemExit(1) from exc


def _handle_completion_command(
    args: argparse.Namespace,
    config: ChrootConfig,
    registry: ChrootRegistry,
    prog: str,
) -> bool:
    if args.command == "completion":
        if args.completion_shell == "zsh":
            sys.stdout.write(generate_zsh_completion(prog))
            return True
        return False

    if args.command != "__complete":
        return False

    values = list(getattr(args, "values", []))
    if args.topic == "chroots":
        sys.stdout.write(completion_chroot_names(registry.list()))
        return True
    if args.topic == "installed-chroots":
        sys.stdout.write(completion_installed_chroot_names(registry.list()))
        return True
    if args.topic == "chroot-details":
        sys.stdout.write(completion_chroot_details(registry.list()))
        return True
    if args.topic == "chroot-preview":
        record = registry.get(values[0] if values else "")
        sys.stdout.write(completion_chroot_preview(record))
        return True
    if args.topic == "users":
        target_name = args.name or (values[0] if values else None)
        if target_name is None:
            installed_names = [str(record["name"]) for record in registry.list() if bool(record.get("installed"))]
            if len(installed_names) == 1:
                target_name = installed_names[0]
        target = config.for_chroot(target_name or config.distro_name)
        sys.stdout.write(completion_user_names(target))
        return True
    if args.topic in {"tools", "addons"}:
        distro = values[0] if values else None
        sys.stdout.write(completion_catalog_names(args.topic, distro=distro))
        return True
    if args.topic in {"tool-categories", "addon-categories"}:
        distro = values[0] if values else None
        sys.stdout.write(completion_catalog_categories(args.topic, distro=distro))
        return True
    if args.topic in {"tool-details", "addon-details"}:
        distro = values[0] if values else None
        category = values[1] if len(values) > 1 else None
        sys.stdout.write(completion_catalog_details(args.topic, distro=distro, category=category))
        return True
    if args.topic in {"tool-preview", "addon-preview"}:
        sys.stdout.write(completion_catalog_preview(args.topic, values[0] if values else ""))
        return True
    return False


def _recovery_command(args: argparse.Namespace) -> str:
    if args.command == "install":
        return f"chrootctl install {args.distro} --resume"
    if args.command == "upgrade":
        return "chrootctl restart"
    if args.command in {"status", "mount", "unmount", "doctor", "fix-tty"}:
        return "chrootctl doctor"
    if args.command == "logs":
        return "chrootctl logs --all --level ERROR"
    if args.command == "chroots":
        return "chrootctl chroots list"
    if args.command == "users":
        return "chrootctl users list"
    if args.command == "tools":
        return "chrootctl tools list"
    if args.command == "addons":
        return "chrootctl addons list"
    return "chrootctl logs --all"
