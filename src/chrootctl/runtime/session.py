from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.text import Text

from ..output import result_panel
from ..catalog import ManifestCatalog
from .catalog import apply_catalog_entries
from .common import console, emit_panel, emit_table, follow_logs, progress_call, read_logs

if TYPE_CHECKING:
    from .core import RuntimeContext


def handle_status(context: RuntimeContext) -> None:
    services = getattr(context, "services", None)
    if services is not None:
        rows = progress_call(
            "Collecting mount status",
            lambda: services.system().status(context.config.distro_name, details=context.args.details),
        )
    else:
        rows = progress_call("Collecting mount status", lambda: context.controller.status(verbose=context.args.details))
        rows = [_status_row(row) for row in rows]
    emit_table(context, "Mount Status", rows)
    if context.args.details:
        record = context.registry.get(context.config.distro_name)
        if record:
            emit_panel(
                context,
                "Chroot",
                {
                    "name": context.config.distro_name,
                    "phase": str(record.get("phase", "")),
                    "installed": str(record.get("installed", "")),
                    "next": _status_next_step(record),
                },
            )


def handle_mount(context: RuntimeContext) -> None:
    result = progress_call("Mounting chroot", context.controller.mount)
    result_panel("Mount", result)


def handle_unmount(context: RuntimeContext) -> None:
    result = progress_call("Unmounting chroot", context.controller.unmount)
    result_panel("Unmount", result)


def handle_fix_tty(context: RuntimeContext) -> None:
    result = progress_call("Fixing tty/devices", context.controller.fix_tty)
    result_panel("Fix TTY", result)


def handle_doctor(context: RuntimeContext) -> None:
    services = getattr(context, "services", None)
    if services is not None:
        rows = progress_call(
            "Running diagnostics",
            lambda: services.system().doctor(context.config.distro_name),
        )
    else:
        raw_rows = progress_call("Running diagnostics", context.controller.doctor)
        rows = [_doctor_row(row, distro=context.config.distro_name) for row in raw_rows]
        record = context.registry.get(context.config.distro_name)
        if record:
            rows.append(
                {
                    "check": "registry",
                    "result": "PASS",
                    "detail": f"phase={record.get('phase')} installed={record.get('installed')}",
                    "next": _status_next_step(record),
                }
            )
        log_exists = context.config.log_file.exists()
        rows.append(
            {
                "check": "log_file",
                "result": "PASS" if log_exists else "WARN",
                "detail": str(context.config.log_file),
                "next": "" if log_exists else "chrootctl logs --all",
            }
        )
    emit_table(context, "Doctor", rows)


def handle_logs(context: RuntimeContext) -> None:
    services = getattr(context, "services", None)
    if services is not None:
        snapshot = services.system().logs(
            context.config.distro_name,
            tail=context.args.tail,
            show_all=context.args.all,
            level=getattr(context.args, "level", None),
            follow=context.args.follow,
        )
        text = snapshot.text
        log_file = snapshot.log_file
    else:
        text = read_logs(
            context.config.log_file,
            tail=context.args.tail,
            show_all=context.args.all,
            level=getattr(context.args, "level", None),
        )
        log_file = context.config.log_file
    body = _logs_body(
        text=text,
        log_file=log_file,
        level=getattr(context.args, "level", None),
        follow=context.args.follow,
    )
    console.print(Panel(Text(body, overflow="fold"), title=f"Logs · {log_file.name}", expand=True))
    if not getattr(context.args, "follow", False):
        return
    try:
        for line in follow_logs(log_file, level=getattr(context.args, "level", None)):
            console.print(line)
    except KeyboardInterrupt:
        return



def _clipboard_wrapper_paths(config) -> dict[str, Path]:
    return {
        "termux-clip": config.chroot_base / "usr" / "local" / "bin" / "termux-clip",
        "xsel": config.chroot_base / "usr" / "local" / "bin" / "xsel",
        "xclip": config.chroot_base / "usr" / "local" / "bin" / "xclip",
    }


def _metadata_names(raw: object) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [name for name in (item.strip() for item in raw.split(",")) if name]


def _record_clipboard_tool(context, record: dict[str, Any]) -> None:
    metadata = dict(record.get("metadata", {}))
    tools = _metadata_names(metadata.get("tools", ""))
    if "setup-clipboard" not in tools:
        tools.append("setup-clipboard")
    metadata["tools"] = ",".join(tools)
    context.registry.upsert(
        name=str(record["name"]),
        distro=str(record["distro"]),
        path=str(record["path"]),
        phase=str(record["phase"]),
        installed=bool(record["installed"]),
        arch=str(record["arch"]) if record.get("arch") is not None else None,
        release_name=str(record["release_name"]) if record.get("release_name") is not None else None,
        version=str(record["version"]) if record.get("version") is not None else None,
        metadata=metadata,
    )


def _ensure_existing_chroot_clipboard_tools(context) -> None:
    registry = getattr(context, "registry", None)
    if registry is None:
        return
    record = registry.get(context.config.distro_name)
    if record is None or not bool(record.get("installed")):
        return
    metadata = record.get("metadata", {})
    applied_tools = _metadata_names(metadata.get("tools", "")) if isinstance(metadata, dict) else []
    if "setup-clipboard" in applied_tools:
        return
    wrappers = _clipboard_wrapper_paths(context.config)
    if all(path.exists() for path in wrappers.values()):
        _record_clipboard_tool(context, record)
        return
    progress_call(
        "Adapting existing chroot clipboard tools",
        lambda: apply_catalog_entries(
            catalog=ManifestCatalog("tool", config=context.config),
            names=["setup-clipboard"],
            config=context.config,
            runner=context.runner,
            registry=context.registry,
            logger=context.logger,
        ),
    )

def handle_start(context: RuntimeContext) -> None:
    _ensure_existing_chroot_clipboard_tools(context)
    context.controller.start_interactive(
        login=context.args.login,
        root_login=context.args.root_login,
        x11=getattr(context.args, "x11", False),
    )


def handle_restart(context: RuntimeContext) -> None:
    _ensure_existing_chroot_clipboard_tools(context)
    context.controller.unmount()
    context.controller.start_interactive(
        login=context.args.login,
        root_login=context.args.root_login,
        x11=getattr(context.args, "x11", False),
    )


def handle_exec(context: RuntimeContext) -> None:
    _ensure_existing_chroot_clipboard_tools(context)
    argv = context.args.argv[1:] if context.args.argv and context.args.argv[0] == "--" else context.args.argv
    code = context.controller.exec(
        root=context.args.root,
        argv=argv or None,
        command=context.args.exec_text,
        x11=getattr(context.args, "x11", False),
    )
    raise SystemExit(code)


def _status_row(row: dict[str, Any]) -> dict[str, str]:
    target = str(row.get("target", ""))
    mounted = str(row.get("mounted", "")).lower() == "yes"
    detail_parts = [target]
    source = str(row.get("source", ""))
    if source:
        detail_parts.append(f"from {source}")
    mount_type = str(row.get("type", ""))
    if mount_type:
        detail_parts.append(f"type={mount_type}")
    if "target_exists" in row:
        detail_parts.append(f"target_exists={row['target_exists']}")
    if "source_exists" in row:
        detail_parts.append(f"source_exists={row['source_exists']}")
    return {
        "check": target or "mount",
        "result": "PASS" if mounted else "WARN",
        "detail": " ".join(part for part in detail_parts if part),
        "next": "" if mounted else "chrootctl mount",
    }


def _doctor_row(row: dict[str, Any], *, distro: str) -> dict[str, str]:
    status = str(row.get("status", "")).lower()
    return {
        "check": str(row.get("check", "")),
        "result": _doctor_result(status),
        "detail": str(row.get("detail", "")),
        "next": _doctor_next_step(str(row.get("check", "")), status, distro=distro),
    }


def _doctor_result(status: str) -> str:
    if status == "ok":
        return "PASS"
    if status in {"warning", "warn"}:
        return "WARN"
    return "FAIL"


def _doctor_next_step(check: str, status: str, *, distro: str) -> str:
    if status == "ok":
        return ""
    if check == "root":
        return "chrootctl mount"
    if check == "mounts":
        return "chrootctl mount"
    if check == "shell":
        return f"chrootctl install {distro} --resume"
    if check == "chroot_base":
        return f"chrootctl install {distro} --resume"
    if check == "busybox":
        return "pkg install busybox"
    if check == "chroot":
        return "pkg install util-linux"
    return "chrootctl doctor"


def _status_next_step(record: dict[str, Any]) -> str:
    installed = bool(record.get("installed"))
    phase = str(record.get("phase", ""))
    if not installed:
        distro = str(record.get("distro", "")) or "ubuntu"
        return f"chrootctl install {distro} --resume"
    if phase and phase != "finalize":
        distro = str(record.get("distro", "")) or "ubuntu"
        return f"chrootctl install {distro} --resume"
    return "chrootctl start"


def _logs_body(*, text: str, log_file, level: str | None, follow: bool) -> str:
    lines = [
        f"path: {log_file}",
        f"level: {level or 'all'}",
        f"mode: {'follow' if follow else 'snapshot'}",
    ]
    if text:
        lines.extend(["", text])
    else:
        lines.append("")
        lines.append("no logs available")
    return "\n".join(lines)
