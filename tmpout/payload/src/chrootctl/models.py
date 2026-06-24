from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


def _display_bool(value: bool) -> str:
    return "yes" if value else "no"


def display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _display_bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return ",".join(display_value(item) for item in value)
    return str(value)


@runtime_checkable
class DisplayRenderable(Protocol):
    def to_display_dict(self) -> dict[str, str]:
        ...


def to_display_dict(value: Mapping[str, Any] | DisplayRenderable) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {str(key): display_value(item) for key, item in value.items()}
    if isinstance(value, DisplayRenderable):
        return value.to_display_dict()
    raise TypeError(f"unsupported display value: {type(value)!r}")


@dataclass(slots=True)
class OperationResult:
    success: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def add_success(self) -> None:
        self.success += 1

    def add_failure(self, message: str) -> None:
        self.failed += 1
        self.errors.append(message)

    def add_skipped(self) -> None:
        self.skipped += 1

    def to_display_dict(self) -> dict[str, str]:
        return {
            "success": display_value(self.success),
            "failed": display_value(self.failed),
            "skipped": display_value(self.skipped),
        }


@dataclass(frozen=True, slots=True)
class ChrootRemovalResult:
    name: str
    removed: bool
    unmounted_success: int
    unmounted_failed: int

    def to_display_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "removed": display_value(self.removed),
            "unmounted_success": display_value(self.unmounted_success),
            "unmounted_failed": display_value(self.unmounted_failed),
        }


@dataclass(frozen=True, slots=True)
class ChrootRenameResult:
    old_name: str
    new_name: str
    renamed: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "old_name": self.old_name,
            "new_name": self.new_name,
            "renamed": display_value(self.renamed),
        }


@dataclass(frozen=True, slots=True)
class ChrootExportResult:
    name: str
    archive: Path
    arch: str

    def to_display_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "archive": display_value(self.archive),
            "arch": self.arch,
        }


@dataclass(frozen=True, slots=True)
class ChrootImportResult:
    name: str
    archive: Path
    arch: str
    path: Path

    def to_display_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "archive": display_value(self.archive),
            "arch": self.arch,
            "path": display_value(self.path),
        }


@dataclass(frozen=True, slots=True)
class ChrootUserDetails:
    username: str
    uid: str
    gid: str
    home: str
    shell: str
    sudo: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "uid": self.uid,
            "gid": self.gid,
            "home": self.home,
            "shell": self.shell,
            "sudo": display_value(self.sudo),
        }


@dataclass(frozen=True, slots=True)
class ChrootUserCreateResult:
    username: str
    shell: str
    sudo: bool
    created: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "shell": self.shell,
            "sudo": display_value(self.sudo),
            "created": display_value(self.created),
        }


@dataclass(frozen=True, slots=True)
class ChrootUserRemoveResult:
    username: str
    home_deleted: bool
    removed: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "home_deleted": display_value(self.home_deleted),
            "removed": display_value(self.removed),
        }


@dataclass(frozen=True, slots=True)
class ChrootUserPasswordResult:
    username: str
    updated: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "password": "updated" if self.updated else "not-updated",
        }


@dataclass(frozen=True, slots=True)
class ChrootUserShellResult:
    username: str
    shell: str
    updated: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "shell": self.shell,
            "updated": display_value(self.updated),
        }


@dataclass(frozen=True, slots=True)
class ChrootUserSudoResult:
    username: str
    enabled: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "sudo": "enabled" if self.enabled else "disabled",
        }


@dataclass(frozen=True, slots=True)
class CatalogApplyResult:
    kind: str
    name: str
    distro: str
    categories: tuple[str, ...]
    applied: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "distro": self.distro,
            "categories": display_value(self.categories),
            "applied": display_value(self.applied),
        }


@dataclass(frozen=True, slots=True)
class InstallExtractResult:
    version: str
    release: str
    tarball: str
    phase: str = "extract"

    def to_display_dict(self) -> dict[str, str]:
        return {
            "phase": self.phase,
            "version": self.version,
            "release": self.release,
            "tarball": self.tarball,
        }


@dataclass(frozen=True, slots=True)
class InstallBootstrapResult:
    username: str
    profile: str
    phase: str = "bootstrap"

    def to_display_dict(self) -> dict[str, str]:
        return {
            "phase": self.phase,
            "username": self.username,
            "profile": self.profile,
        }


@dataclass(frozen=True, slots=True)
class InstallDesktopResult:
    desktop: str
    snapshot: str
    profile: str
    phase: str = "desktop"

    def to_display_dict(self) -> dict[str, str]:
        return {
            "phase": self.phase,
            "desktop": self.desktop,
            "snapshot": self.snapshot,
            "profile": self.profile,
        }


@dataclass(frozen=True, slots=True)
class InstallFinalizeResult:
    installed: bool
    uid_sync: bool
    snapshot: str
    status: str | None = None
    phase: str = "finalize"

    def to_display_dict(self) -> dict[str, str]:
        data = {
            "phase": self.phase,
            "installed": display_value(self.installed),
            "uid_sync": display_value(self.uid_sync),
            "snapshot": self.snapshot,
        }
        if self.status:
            data["status"] = self.status
        return data


@dataclass(frozen=True, slots=True)
class InstallAlreadyCompleteResult:
    installed: bool = True
    status: str = "already_complete"
    phase: str = "finalize"

    def to_display_dict(self) -> dict[str, str]:
        return {
            "phase": self.phase,
            "installed": display_value(self.installed),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    status: str
    snapshot: str
    next_steps: tuple[str, ...] = ()

    def to_display_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "snapshot": self.snapshot,
            "next_steps": display_value(self.next_steps),
        }


InstallerResult = (
    InstallExtractResult
    | InstallBootstrapResult
    | InstallDesktopResult
    | InstallFinalizeResult
    | InstallAlreadyCompleteResult
)


@dataclass(frozen=True, slots=True)
class UserIdStatus:
    username: str
    host_uid: int
    host_gid: int
    chroot_uid: str
    chroot_gid: str
    passwd_exists: bool
    group_exists: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "host_uid": display_value(self.host_uid),
            "host_gid": display_value(self.host_gid),
            "chroot_uid": self.chroot_uid,
            "chroot_gid": self.chroot_gid,
            "passwd_exists": display_value(self.passwd_exists),
            "group_exists": display_value(self.group_exists),
        }


@dataclass(frozen=True, slots=True)
class UserIdSyncResult:
    username: str
    uid: int
    gid: int
    ownership_fixed: bool

    def to_display_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "uid": display_value(self.uid),
            "gid": display_value(self.gid),
            "ownership_fixed": display_value(self.ownership_fixed),
        }


@dataclass(frozen=True, slots=True)
class ChrootRecord:
    name: str
    distro: str
    path: str
    release_name: str
    version: str
    phase: str
    installed: bool
    created_at: str
    updated_at: str

    def to_display_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "distro": self.distro,
            "path": self.path,
            "release_name": self.release_name,
            "version": self.version,
            "phase": self.phase,
            "installed": display_value(self.installed),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ChrootDetails:
    name: str
    distro: str
    path: str
    release_name: str
    version: str
    phase: str
    installed: bool
    arch: str
    created_at: str
    updated_at: str
    configured_mounts: str
    extra_packages: str
    locale: str
    metadata: dict[str, str] = field(default_factory=dict)

    def to_display_dict(self) -> dict[str, str]:
        data = {
            "name": self.name,
            "distro": self.distro,
            "path": self.path,
            "release_name": self.release_name,
            "version": self.version,
            "phase": self.phase,
            "installed": display_value(self.installed),
            "arch": self.arch,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "configured_mounts": self.configured_mounts,
            "extra_packages": self.extra_packages,
            "locale": self.locale,
        }
        for key, value in self.metadata.items():
            data[f"metadata.{key}"] = value
        return data


@dataclass(frozen=True, slots=True)
class CheckRow:
    check: str
    result: str
    detail: str
    next: str = ""

    def to_display_dict(self) -> dict[str, str]:
        return {
            "check": self.check,
            "result": self.result,
            "detail": self.detail,
            "next": self.next,
        }


@dataclass(frozen=True, slots=True)
class LogLink:
    label: str
    href: str

    def to_display_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "href": self.href,
        }


@dataclass(frozen=True, slots=True)
class LogEntry:
    line: str
    level: str | None = None
    links: tuple[LogLink, ...] = ()

    def to_display_dict(self) -> dict[str, str]:
        return {
            "line": self.line,
            "level": self.level or "",
            "links": display_value([link.to_display_dict() for link in self.links]),
        }


@dataclass(frozen=True, slots=True)
class LogSnapshot:
    log_file: Path
    level: str | None
    lines: tuple[str, ...]
    follow: bool = False
    target_name: str | None = None
    entries: tuple[LogEntry, ...] = ()
    related_links: tuple[LogLink, ...] = ()

    @property
    def text(self) -> str:
        if self.entries:
            return "\n".join(entry.line for entry in self.entries)
        return "\n".join(self.lines)

    def to_display_dict(self) -> dict[str, str]:
        return {
            "log_file": display_value(self.log_file),
            "level": self.level or "",
            "lines": display_value(list(self.lines)),
            "follow": display_value(self.follow),
            "target_name": self.target_name or "",
            "entries": display_value([entry.to_display_dict() for entry in self.entries]),
            "related_links": display_value([link.to_display_dict() for link in self.related_links]),
        }


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    target_name: str | None
    chroots: tuple[ChrootRecord, ...]
    status_checks: tuple[CheckRow, ...]
    doctor_checks: tuple[CheckRow, ...]
    logs: LogSnapshot | None = None


@dataclass(frozen=True, slots=True)
class InstallWizardDefaults:
    distro: str | None = None
    name: str | None = None
    username: str | None = None
    profile: str | None = None
    desktop: str | None = None
    release: str | None = None
    version: str | None = None
    tools: tuple[str, ...] = ()
    addons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InstallRequest:
    distro: str
    name: str
    username: str
    profile: str | None = None
    desktop: str | None = None
    release: str | None = None
    version: str | None = None
    phase: str | None = None
    force_phase: bool = False
    resume: bool = False
    repair: bool = False
    tools: tuple[str, ...] = ()
    addons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InstallRunResult:
    chroot_name: str
    distro: str
    phases: tuple[InstallerResult, ...]
    tool_results: tuple[CatalogApplyResult, ...] = ()
    addon_results: tuple[CatalogApplyResult, ...] = ()
    next_steps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SessionActionResult:
    action: str
    target: str
    exit_code: int
    next_steps: tuple[str, ...] = ()

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def to_display_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "target": self.target,
            "exit_code": display_value(self.exit_code),
            "success": display_value(self.success),
            "next_steps": display_value(self.next_steps),
        }


@dataclass(frozen=True, slots=True)
class DashboardChrootCard:
    name: str
    distro: str
    phase: str
    installed: bool
    running: bool
    user_count: int
    doctor_warnings: int = 0
    doctor_failures: int = 0

    def to_display_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "distro": self.distro,
            "phase": self.phase,
            "installed": display_value(self.installed),
            "running": display_value(self.running),
            "user_count": display_value(self.user_count),
            "doctor_warnings": display_value(self.doctor_warnings),
            "doctor_failures": display_value(self.doctor_failures),
        }
