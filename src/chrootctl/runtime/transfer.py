from __future__ import annotations

from typing import TYPE_CHECKING

from .common import emit_panel, progress_call
from .resolution import resolve_chroot_name

if TYPE_CHECKING:
    from .core import RuntimeContext


def handle_transfer(context: RuntimeContext) -> None:
    args = context.args
    non_interactive = bool(getattr(args, "non_interactive", False))
    if args.transfer_command == "export":
        chroot_name = resolve_chroot_name(
            args.name,
            context.registry,
            prompt="Choose chroot to export",
            auto_select_single=True,
            non_interactive=non_interactive,
        )
        result = progress_call("Exporting chroot", lambda: context.services.chroots().export(chroot_name, archive=args.archive, password=getattr(args, "password", None)))
        emit_panel(context, "Chroot Export", result)
        return
    if args.transfer_command == "inspect":
        result = progress_call("Inspecting archive", lambda: context.services.chroots().inspect_archive(args.archive, password=getattr(args, "password", None)))
        emit_panel(context, "Chroot Transfer Inspect", result)
        return
    if args.transfer_command == "import":
        result = progress_call("Importing chroot", lambda: context.services.chroots().import_archive(args.archive, name=args.import_name, conflict=args.conflict, password=getattr(args, "password", None), post_import=getattr(args, "post_import", "register")))
        emit_panel(context, "Chroot Import", result)
        return
    raise RuntimeError(f"unsupported transfer command: {args.transfer_command}")
