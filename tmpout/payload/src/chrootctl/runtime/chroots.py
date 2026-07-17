from __future__ import annotations
from ..services.chroots import remove_chroot, rename_chroot

from typing import TYPE_CHECKING

from .common import emit_panel, emit_table, progress_call
from .confirm import confirm_action
from .resolution import resolve_chroot_name

if TYPE_CHECKING:
    from .core import RuntimeContext


def handle_chroots(context: RuntimeContext) -> None:
    args = context.args
    non_interactive = bool(getattr(args, "non_interactive", False))
    if args.chroots_command == "list":
        emit_table(context, "Installed Chroots", context.services.chroots().list())
        return
    if args.chroots_command == "show":
        chroot_name = resolve_chroot_name(args.name, context.registry, prompt="Choose chroot", auto_select_single=True, non_interactive=non_interactive)
        emit_panel(context, "Chroot Details", context.services.chroots().get(chroot_name))
        return
    if args.chroots_command == "remove":
        chroot_name = resolve_chroot_name(args.name, context.registry, prompt="Choose chroot to remove", auto_select_single=True, non_interactive=non_interactive)
        confirm_action(f"Remove chroot '{chroot_name}'?", assume_yes=args.yes, non_interactive=non_interactive)
        result = progress_call("Removing chroot", lambda: context.services.chroots().remove(chroot_name))
        emit_panel(context, "Chroot Remove", result)
        return
    if args.chroots_command == "rename":
        old_name = resolve_chroot_name(args.name, context.registry, prompt="Choose chroot to rename", auto_select_single=True, non_interactive=non_interactive)
        if not args.new_name:
            raise RuntimeError("new chroot name is required")
        result = progress_call("Renaming chroot", lambda: context.services.chroots().rename(old_name, args.new_name))
        emit_panel(context, "Chroot Rename", result)
        return
    if args.chroots_command == "export":
        chroot_name = resolve_chroot_name(args.name, context.registry, prompt="Choose chroot to export", auto_select_single=True, non_interactive=non_interactive)
        result = progress_call("Exporting chroot", lambda: context.services.chroots().export(chroot_name, archive=args.archive, password=getattr(args, "password", None)))
        emit_panel(context, "Chroot Export", result)
        return
    if args.chroots_command == "import":
        result = progress_call("Importing chroot", lambda: context.services.chroots().import_archive(args.archive, name=args.import_name, conflict=args.conflict, password=getattr(args, "password", None), post_import=getattr(args, "post_import", "register")))
        emit_panel(context, "Chroot Import", result)
        return
    if args.chroots_command == "diff":
        result = progress_call("Comparing package inventories", lambda: context.services.chroots().package_diff(args.left_name, args.right_name))
        emit_panel(context, "Chroot Package Diff", result)
        return
    if args.chroots_command == "validate-import":
        chroot_name = resolve_chroot_name(getattr(args, "validate_name", None) or args.name, context.registry, prompt="Choose imported chroot", auto_select_single=True, non_interactive=non_interactive)
        result = progress_call("Validating imported chroot", lambda: context.services.chroots().validate_imported(chroot_name))
        emit_panel(context, "Imported Chroot Validation", result)
        return
    raise RuntimeError(f"unsupported chroots command: {args.chroots_command}")
