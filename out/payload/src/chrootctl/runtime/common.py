from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from ..config import ChrootConfig
from ..output import build_console, render_table, result_panel

console = build_console()

DEFAULT_LOG_TAIL = 100

MACHINE_READABLE_COMMANDS = frozenset({"status", "doctor", "chroots", "users", "tools", "addons"})
LOG_LEVEL_VALUES = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}
_LOG_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")


def progress_call(description: str, fn, *, interactive: bool = False):
    if interactive:
        return fn()
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


def wants_json(context: Any) -> bool:
    return bool(getattr(context.args, "json", False)) and getattr(context.args, "command", "") in MACHINE_READABLE_COMMANDS


def ensure_json_supported(args: Any) -> None:
    if bool(getattr(args, "json", False)) and getattr(args, "command", "") not in MACHINE_READABLE_COMMANDS:
        raise RuntimeError(f"--json is not supported for command: {getattr(args, 'command', '')}")


def emit_table(context: Any, title: str, rows) -> None:
    render_table(title, rows, json_output=wants_json(context))


def emit_panel(context: Any, title: str, data) -> None:
    result_panel(title, data, json_output=wants_json(context))


def flatten_record(record: dict[str, object]) -> dict[str, str]:
    data = {key: str(value) for key, value in record.items() if key != "metadata_json"}
    metadata = record.get("metadata", {})
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            data[f"metadata.{key}"] = str(value)
    return data


def read_logs(
    log_file: Path,
    *,
    tail: int,
    show_all: bool,
    level: str | None = None,
) -> str:
    if not log_file.exists():
        return ""
    lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    filtered = filter_log_lines(lines, level=level)
    if show_all:
        return "\n".join(filtered)
    return "\n".join(filtered[-(tail or DEFAULT_LOG_TAIL):])


def follow_logs(
    log_file: Path,
    *,
    level: str | None = None,
    poll_interval: float = 0.2,
):
    threshold = _level_threshold(level)
    current_keep = threshold is None
    stream = None

    while True:
        if stream is None:
            if not log_file.exists():
                time.sleep(poll_interval)
                continue
            stream = log_file.open("r", encoding="utf-8", errors="ignore")
            stream.seek(0, 2)

        line = stream.readline()
        if not line:
            time.sleep(poll_interval)
            continue

        stripped = line.rstrip("\n")
        matched_level = _matched_log_level(stripped)
        if matched_level is not None:
            current_keep = threshold is None or LOG_LEVEL_VALUES[matched_level] >= threshold
        if threshold is None or current_keep:
            yield stripped


def filter_log_lines(lines: list[str], *, level: str | None = None) -> list[str]:
    threshold = _level_threshold(level)
    if threshold is None:
        return list(lines)

    filtered: list[str] = []
    current_keep = False
    for line in lines:
        matched_level = _matched_log_level(line)
        if matched_level is not None:
            current_keep = LOG_LEVEL_VALUES[matched_level] >= threshold
        if current_keep:
            filtered.append(line)
    return filtered


def mount_summary(config: ChrootConfig) -> str:
    mounts = list(config.media_mounts) + list(config.extra_bind_mounts)
    if not mounts:
        return "none"
    return ", ".join(
        f"{mount.source}->{mount.target}{':ro' if mount.read_only else ''}"
        for mount in mounts
        if mount.enabled
    )


def _level_threshold(level: str | None) -> int | None:
    if not level:
        return None
    return LOG_LEVEL_VALUES[str(level).upper()]


def _matched_log_level(line: str) -> str | None:
    match = _LOG_LEVEL_RE.search(line)
    if match is None:
        return None
    return match.group(1)
