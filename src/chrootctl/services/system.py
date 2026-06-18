from __future__ import annotations

import re

from ..models import CheckRow, DashboardSummary, LogEntry, LogLink, LogSnapshot
from ..runtime.common import read_logs
from .chroots import record_from_registry
from .context import ServiceContainer

_CATALOG_LINK_RE = re.compile(r"\bapplied\s+(?P<kind>tool|addon)s?\s+(?P<entry>[A-Za-z0-9][A-Za-z0-9._-]*)\b", re.IGNORECASE)
_LOG_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")


class SystemService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def dashboard(self, *, target_name: str | None = None, details: bool = False, tail: int = 20) -> DashboardSummary:
        selected = target_name or _default_target_name(self.services)
        status_checks = tuple(self.status(selected, details=details)) if selected else ()
        doctor_checks = tuple(self.doctor(selected)) if selected else ()
        logs = self.logs(selected, tail=tail) if selected else None
        return DashboardSummary(
            target_name=selected,
            chroots=tuple(record_from_registry(row) for row in self.services.registry.list()),
            status_checks=status_checks,
            doctor_checks=doctor_checks,
            logs=logs,
        )

    def status(self, name: str, *, details: bool = False) -> list[CheckRow]:
        runtime = self.services.runtime_for(name)
        rows = [_status_row(row) for row in runtime.controller.status(verbose=details)]
        if details:
            record = self.services.registry.get(name)
            if record:
                rows.append(
                    CheckRow(
                        check="chroot",
                        result="PASS" if bool(record.get("installed")) else "WARN",
                        detail=f"phase={record.get('phase', '')} installed={bool(record.get('installed'))}",
                        next=_status_next_step(record),
                    )
                )
        return rows

    def doctor(self, name: str) -> list[CheckRow]:
        runtime = self.services.runtime_for(name)
        rows = [_doctor_row(row, distro=runtime.config.distro_name) for row in runtime.controller.doctor()]
        record = self.services.registry.get(name)
        if record:
            rows.append(CheckRow(check="registry", result="PASS", detail=f"phase={record.get('phase')} installed={record.get('installed')}", next=_status_next_step(record)))
        log_exists = runtime.config.log_file.exists()
        rows.append(CheckRow(check="log_file", result="PASS" if log_exists else "WARN", detail=str(runtime.config.log_file), next="" if log_exists else "chrootctl logs --all"))
        return rows

    def logs(self, name: str | None, *, tail: int = 100, show_all: bool = False, level: str | None = None, follow: bool = False) -> LogSnapshot:
        config = self.services.config_for(name)
        text = read_logs(config.log_file, tail=tail, show_all=show_all, level=level)
        lines = tuple(text.splitlines())
        related_links = _log_related_links(name)
        entries = tuple(_build_log_entry(line) for line in lines)
        return LogSnapshot(
            log_file=config.log_file,
            level=level.upper() if level else None,
            lines=lines,
            follow=follow,
            target_name=name,
            entries=entries,
            related_links=related_links,
        )


def _default_target_name(services: ServiceContainer) -> str | None:
    rows = services.registry.list()
    if len(rows) == 1:
        return str(rows[0].get("name", ""))
    installed = [row for row in rows if bool(row.get("installed"))]
    if len(installed) == 1:
        return str(installed[0].get("name", ""))
    return None


def _status_row(row: dict[str, object]) -> CheckRow:
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
    return CheckRow(
        check=target or "mount",
        result="PASS" if mounted else "WARN",
        detail=" ".join(part for part in detail_parts if part),
        next="" if mounted else "chrootctl mount",
    )


def _doctor_row(row: dict[str, object], *, distro: str) -> CheckRow:
    status = str(row.get("status", "")).lower()
    return CheckRow(
        check=str(row.get("check", "")),
        result=_doctor_result(status),
        detail=str(row.get("detail", "")),
        next=_doctor_next_step(str(row.get("check", "")), status, distro=distro),
    )


def _doctor_result(status: str) -> str:
    if status == "ok":
        return "PASS"
    if status in {"warning", "warn"}:
        return "WARN"
    return "FAIL"


def _doctor_next_step(check: str, status: str, *, distro: str) -> str:
    if status == "ok":
        return ""
    if check == "mounts":
        return "chrootctl mount"
    if check == "tty":
        return "chrootctl fix-tty"
    if check == "shell":
        return f"chrootctl --name {distro} users shell root --shell /bin/bash"
    return "chrootctl doctor"


def _status_next_step(record: dict[str, object]) -> str:
    phase = str(record.get("phase", ""))
    if not bool(record.get("installed")):
        return "chrootctl install --resume"
    if phase == "finalize":
        return "chrootctl start"
    return "chrootctl status --details"


def _log_related_links(name: str | None) -> tuple[LogLink, ...]:
    if not name:
        return ()
    return (
        LogLink(label=f"Chroot · {name}", href=f"/chroots/{name}"),
        LogLink(label=f"Users · {name}", href=f"/chroots/{name}/users"),
        LogLink(label=f"Status · {name}", href=f"/status?name={name}"),
        LogLink(label=f"Doctor · {name}", href=f"/doctor?name={name}"),
    )


def _build_log_entry(line: str) -> LogEntry:
    links: list[LogLink] = []
    for match in _CATALOG_LINK_RE.finditer(line):
        kind = match.group("kind").lower()
        entry = match.group("entry")
        href = f"/tools/{entry}" if kind == "tool" else f"/addons/{entry}"
        links.append(LogLink(label=f"{kind} · {entry}", href=href))
    return LogEntry(line=line, level=_log_level(line), links=tuple(links))


def _log_level(line: str) -> str | None:
    match = _LOG_LEVEL_RE.search(line)
    if match is None:
        return None
    return match.group(1)
