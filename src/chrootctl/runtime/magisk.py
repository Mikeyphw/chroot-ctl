from __future__ import annotations

from pathlib import Path

from ..magisk import MagiskModuleConfig, render_magisk_module, resolve_startup_targets, validate_magisk_module, zip_magisk_module
from ..output import result_panel
from .common import progress_call

if False:  # pragma: no cover
    from .core import RuntimeContext


def handle_magisk(context: "RuntimeContext") -> None:
    if context.args.magisk_command == "render":
        _handle_render(context)
        return
    raise RuntimeError(f"unsupported magisk command: {context.args.magisk_command}")


def _handle_render(context: "RuntimeContext") -> None:
    selected_names = tuple(context.args.magisk_names or ())
    startup_targets = resolve_startup_targets(
        context.services,
        selected_names=selected_names,
        all_installed=bool(context.args.all_installed),
    )
    result = progress_call(
        "Rendering Magisk module",
        lambda: render_magisk_module(
            Path(context.args.output),
            services=context.services,
            startup_targets=startup_targets,
            module_config=MagiskModuleConfig(),
        ),
    )
    validate_magisk_module(result.output_dir)
    details = {
        "output_dir": result.output_dir,
        "startup_targets": ", ".join(startup_targets) or "none",
        "files": len(result.files),
        "service_sh": result.output_dir / "service.sh",
        "post_fs_data_sh": result.output_dir / "post-fs-data.sh",
    }
    if getattr(context.args, "zip_path", None):
        zip_path = zip_magisk_module(result.output_dir, Path(context.args.zip_path))
        details["zip"] = zip_path
    result_panel("Magisk", details)
