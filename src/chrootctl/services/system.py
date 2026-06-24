from __future__ import annotations

import os
import re
import shutil
import socket

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



    def quickstart(self) -> dict[str, object]:
        host_rows = self.host_doctor()
        blockers = [row for row in host_rows if getattr(row, "result", "") == "FAIL"]
        warnings = [row for row in host_rows if getattr(row, "result", "") == "WARN"]
        chroots = self.services.chroots().list()
        recommended_name = _recommended_quickstart_name(chroots)
        install_state: dict[str, object]
        try:
            install_state = self.services.install().install_form_state(name=recommended_name)
        except Exception:
            install_state = {
                "defaults": {
                    "distro": "ubuntu",
                    "name": recommended_name,
                    "username": None,
                    "preset": "minimal-server",
                    "profile": "minimal",
                    "desktop": "none",
                    "release": "noble",
                    "version": None,
                    "mirror": "auto",
                },
                "users": [],
            }
        defaults = dict(install_state.get("defaults", {}))
        users = list(install_state.get("users", []))
        target_user = defaults.get("username") or (users[0]["name"] if users else "")
        can_install = not blockers and bool(target_user)
        shell_target = chroots[0].name if chroots else None
        use_steps = [
            "Open Install and review the guided plan.",
            "Pick or create a target user, then start the install job.",
            "Open the created chroot and copy the shell command.",
        ]
        if shell_target:
            use_steps[-1] = f"Open {shell_target} and copy the shell command."
        return {
            "host_rows": host_rows,
            "blockers": blockers,
            "warnings": warnings,
            "chroot_count": len(chroots),
            "recommended_name": recommended_name,
            "defaults": defaults,
            "target_user": target_user,
            "can_install": can_install,
            "shell_target": shell_target,
            "shell_command": f"chrootctl --name {shell_target} start --login" if shell_target else "",
            "install_command": _quickstart_install_command(defaults, target_user=target_user),
            "use_steps": use_steps,
        }

    def host_doctor(self) -> list[CheckRow]:
        runner = self.services.runtime_for().runner
        host_arch = runner.host_arch()
        base_config = self.services.base_config
        checks = [
            CheckRow(
                check="python_runtime",
                result="PASS",
                detail="Python runtime available for CLI and Web UI.",
                next="",
            ),
            CheckRow(
                check="tar",
                result="PASS" if runner.command_exists("tar") else "FAIL",
                detail="tar available" if runner.command_exists("tar") else "tar command not found on host.",
                next="" if runner.command_exists("tar") else "Install tar on the host before exporting or importing archives.",
            ),
            CheckRow(
                check="zstd",
                result="PASS" if runner.command_exists("zstd") else "FAIL",
                detail="zstd available" if runner.command_exists("zstd") else "zstd command not found on host.",
                next="" if runner.command_exists("zstd") else "Install zstd on the host before working with tar.zst archives.",
            ),
            CheckRow(
                check="root_access",
                result="PASS" if _has_root_access() else "WARN",
                detail="Root access is available." if _has_root_access() else "Current process is not running as root.",
                next="" if _has_root_access() else "Use sudo/root for installs, mounts, and package operations.",
            ),
            CheckRow(
                check="network",
                result="PASS" if _network_ready() else "WARN",
                detail="Basic DNS/network lookup succeeded." if _network_ready() else "Could not confirm DNS/network access from the host.",
                next="" if _network_ready() else "Check network connectivity before bootstrap or package downloads.",
            ),
            _path_check("chroot_root", base_config.chroot_root, create=True, blocker=True),
            _path_check("log_file_dir", base_config.log_file.parent, create=True, blocker=True),
            _path_check("database_dir", base_config.database_path.parent, create=True, blocker=True),
            _command_check(runner, "busybox", blocker=True, message="busybox is required for mount and chroot helpers."),
            _command_check(runner, "curl", blocker=False, message="curl is recommended for rootfs downloads."),
            _command_check(runner, "openssl", blocker=False, message="openssl is needed for encrypted export/import archives."),
        ]
        for arch in ("arm64", "amd64"):
            checks.extend(self.cross_arch_rows(target_arch=arch, host_arch=host_arch))
        return checks

    def cross_arch_rows(self, *, target_arch: str, host_arch: str | None = None) -> list[CheckRow]:
        runner = self.services.runtime_for().runner
        host = host_arch or runner.host_arch()
        native = target_arch == host
        qemu_name = f"qemu-{target_arch}-static"
        qemu_ready = runner.command_exists(qemu_name)
        binfmt_ready = native or runner.can_execute_foreign_arch(target_arch)
        return [
            CheckRow(
                check=f"{target_arch}_qemu",
                result="PASS" if native or qemu_ready else "WARN",
                detail=f"Native host architecture {host}." if native else (f"{qemu_name} detected." if qemu_ready else f"{qemu_name} not found on host."),
                next="" if native or qemu_ready else f"Install {qemu_name} to continue foreign-arch phases on this host.",
            ),
            CheckRow(
                check=f"{target_arch}_binfmt",
                result="PASS" if native or binfmt_ready else "WARN",
                detail="Native execution path available." if native else ("binfmt_misc is ready for this target." if binfmt_ready else "binfmt_misc is not enabled for this target."),
                next="" if native or binfmt_ready else "Enable qemu binfmt support or export the extract-phase rootfs to the target device.",
            ),
        ]

    def cross_arch_state(self) -> dict[str, object]:
        runner = self.services.runtime_for().runner
        host_arch = runner.host_arch()
        targets = []
        for arch in ("arm64", "amd64"):
            native = arch == host_arch
            qemu_ready = runner.command_exists(f"qemu-{arch}-static")
            binfmt_ready = native or runner.can_execute_foreign_arch(arch)
            targets.append(
                {
                    "arch": arch,
                    "native": native,
                    "qemu_ready": native or qemu_ready,
                    "binfmt_ready": native or binfmt_ready,
                    "ready": native or (qemu_ready and binfmt_ready),
                    "mode": "native" if native else ("foreign-ready" if qemu_ready and binfmt_ready else "extract-only"),
                    "guidance": _cross_arch_guidance(host_arch, arch, qemu_ready=native or qemu_ready, binfmt_ready=native or binfmt_ready),
                }
            )
        return {"host_arch": host_arch, "targets": targets}

    def foreign_arch_advisories(self) -> list[dict[str, str]]:
        host_arch = self.services.runtime_for().runner.host_arch()
        advisories: list[dict[str, str]] = []
        for chroot in self.services.chroots().list():
            try:
                details = self.services.chroots().get(chroot.name)
            except Exception:
                continue
            if details.arch == host_arch:
                continue
            mode = "ready" if self.services.runtime_for().runner.can_execute_foreign_arch(details.arch) else "deferred"
            advisories.append(
                {
                    "name": details.name,
                    "arch": details.arch,
                    "phase": details.phase,
                    "installed": "yes" if details.installed else "no",
                    "mode": mode,
                    "summary": _foreign_arch_summary(name=details.name, arch=details.arch, phase=details.phase, installed=details.installed, mode=mode),
                }
            )
        return advisories

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


def _has_root_access() -> bool:
    return hasattr(shutil, "which") and hasattr(__import__("os"), "geteuid") and __import__("os").geteuid() == 0


def _network_ready() -> bool:
    try:
        socket.getaddrinfo("archive.ubuntu.com", 80, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return True


def _cross_arch_guidance(host_arch: str, target_arch: str, *, qemu_ready: bool, binfmt_ready: bool) -> str:
    if host_arch == target_arch:
        return "This target matches the host architecture."
    if qemu_ready and binfmt_ready:
        return "Foreign-arch bootstrap can continue on this host with qemu + binfmt."
    return "Extract now, then export/import to the target device for finalize later."


def _foreign_arch_summary(*, name: str, arch: str, phase: str, installed: bool, mode: str) -> str:
    if mode == "ready":
        return f"{name} targets {arch} and can continue on this host."
    if phase == "extract" or not installed:
        return f"{name} targets {arch}; extract is ready to export and finalize on-device later."
    return f"{name} targets {arch}; host emulation is not ready, so finalize on-device later."


def _recommended_quickstart_name(chroots: list[object]) -> str:
    existing = {getattr(item, "name", "") for item in chroots}
    base = "ubuntu"
    if base not in existing:
        return base
    index = 2
    while f"{base}-{index}" in existing:
        index += 1
    return f"{base}-{index}"


def _quickstart_install_command(defaults: dict[str, object], *, target_user: str) -> str:
    distro = str(defaults.get("distro") or "ubuntu")
    name = str(defaults.get("name") or "ubuntu")
    preset = str(defaults.get("preset") or "minimal-server")
    release = str(defaults.get("release") or "noble")
    command = f"sudo chrootctl install {distro} --name {name} --preset {preset} --release {release}"
    if target_user:
        command += f" --username {target_user}"
    return command


def _path_check(name: str, path: Path, *, create: bool, blocker: bool) -> CheckRow:
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        writable = path.exists() and os.access(path, os.W_OK)
        return CheckRow(
            check=name,
            result="PASS" if writable else ("FAIL" if blocker else "WARN"),
            detail=f"{path} is ready." if writable else f"{path} is not writable.",
            next="" if writable else f"Create or fix permissions for {path}.",
        )
    except Exception as exc:
        return CheckRow(
            check=name,
            result="FAIL" if blocker else "WARN",
            detail=f"{path} could not be prepared: {exc}",
            next=f"Create or fix permissions for {path}.",
        )


def _command_check(runner, command: str, *, blocker: bool, message: str) -> CheckRow:
    ready = runner.command_exists(command)
    return CheckRow(
        check=command,
        result="PASS" if ready else ("FAIL" if blocker else "WARN"),
        detail=f"{command} available" if ready else message,
        next="" if ready else f"Install {command} on the host.",
    )
