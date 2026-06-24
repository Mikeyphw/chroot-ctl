from __future__ import annotations

from ..config import ChrootConfig
from .common import emit_panel, emit_table, progress_call
from .confirm import confirm_action
from .resolution import resolve_user_reference, resolve_username


def handle_users(context) -> None:
    args = context.args
    user_manager = context.chroot_users
    services = getattr(context, "services", None)
    user_service = services.users(name=context.config.distro_name) if services is not None else None
    non_interactive = bool(getattr(args, "non_interactive", False))
    if args.users_command == "show-id":
        username = resolve_user_reference(args.username, user_manager, prompt="Choose user", non_interactive=non_interactive)
        emit_panel(context, "User IDs", user_service.show_id(username) if user_service is not None else context.user_sync.show_id(username=username))
        return
    if args.users_command == "sync-id":
        username = resolve_user_reference(args.username, user_manager, prompt="Choose user", non_interactive=non_interactive)
        result = progress_call(
            "Syncing user IDs",
            lambda: user_service.sync_id(username, fix_ownership=not args.no_fix_ownership) if user_service is not None else context.user_sync.sync_id(username=username, fix_ownership=not args.no_fix_ownership),
        )
        emit_panel(context, "User Sync", result)
        return
    if args.users_command == "list":
        emit_table(context, "Chroot Users", user_service.list() if user_service is not None else user_manager.user_rows())
        return
    if args.users_command == "show":
        username = resolve_username(args.username, user_manager, prompt="Choose user", non_interactive=non_interactive)
        emit_panel(context, "Chroot User", user_service.show(username) if user_service is not None else user_manager.show_user(username))
        return
    if args.users_command == "add":
        if not args.username:
            raise RuntimeError("username is required")
        result = progress_call(
            "Adding chroot user",
            lambda: user_service.add(args.username, shell=args.shell, sudo=args.sudo) if user_service is not None else user_manager.add_user(args.username, shell=args.shell, sudo=args.sudo),
        )
        emit_panel(context, "Chroot User Add", result)
        return
    if args.users_command == "remove":
        username = resolve_username(args.username, user_manager, prompt="Choose user to remove", non_interactive=non_interactive)
        confirm_action(f"Remove user '{username}'?", assume_yes=args.yes, non_interactive=non_interactive)
        result = progress_call(
            "Removing chroot user",
            lambda: user_service.remove(username, delete_home=args.delete_home) if user_service is not None else user_manager.remove_user(username, delete_home=args.delete_home),
        )
        emit_panel(context, "Chroot User Remove", result)
        return
    if args.users_command == "password":
        username = resolve_username(args.username, user_manager, prompt="Choose user", non_interactive=non_interactive)
        result = progress_call("Updating user password", lambda: user_service.set_password(username) if user_service is not None else user_manager.set_password(username), interactive=True)
        emit_panel(context, "Chroot User Password", result)
        return
    if args.users_command == "shell":
        username = resolve_username(args.username, user_manager, prompt="Choose user", non_interactive=non_interactive)
        result = progress_call(
            "Updating user shell",
            lambda: user_service.set_shell(username, shell=args.shell) if user_service is not None else user_manager.set_shell(username, shell=args.shell),
        )
        emit_panel(context, "Chroot User Shell", result)
        return
    if args.users_command == "sudo":
        username = resolve_username(args.username, user_manager, prompt="Choose user", non_interactive=non_interactive)
        result = progress_call(
            "Updating user sudo",
            lambda: user_service.set_sudo(username, enabled=args.enable) if user_service is not None else user_manager.set_sudo(username, enabled=args.enable),
        )
        emit_panel(context, "Chroot User Sudo", result)
        return
    raise RuntimeError(f"unsupported users command: {args.users_command}")


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
