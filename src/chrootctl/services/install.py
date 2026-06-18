from __future__ import annotations

import os
from collections.abc import Callable

from ..base_install import ReleaseRef
from ..installer_factory import build_installer
from ..models import InstallRequest, InstallRunResult, InstallWizardDefaults, UpgradeResult
from ..user_sync import validate_username
from .context import ServiceContainer

PROFILE_OPTIONS = ("minimal", "dev", "xfce4", "plasma", "custom")
DESKTOP_OPTIONS = ("auto", "none", "xfce4", "plasma")
DISTRO_OPTIONS = ("ubuntu", "arch")


class InstallService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def distros(self) -> tuple[str, ...]:
        return DISTRO_OPTIONS

    def profiles(self) -> tuple[str, ...]:
        return PROFILE_OPTIONS

    def desktops(self) -> tuple[str, ...]:
        return DESKTOP_OPTIONS

    def wizard_defaults(self, *, name: str | None = None, distro: str | None = None) -> InstallWizardDefaults:
        record = _preferred_record(self.services, name=name, distro=distro)
        selected_distro = distro
        selected_name = name
        release = None
        version = None
        profile = None
        desktop = None
        username = None
        if record is not None:
            selected_distro = selected_distro or str(record.get("distro") or "") or None
            selected_name = selected_name or str(record.get("name") or "") or None
            release = str(record.get("release_name") or "") or None
            version = str(record.get("version") or "") or None
            metadata = record.get("metadata", {})
            if isinstance(metadata, dict):
                profile = _metadata_value(metadata, "profile")
                desktop = _metadata_value(metadata, "desktop")
                username = _validated_username(_metadata_value(metadata, "username"))
        selected_name = selected_name or selected_distro
        username = username or _default_username_hint(self.services, selected_name)
        return InstallWizardDefaults(
            distro=selected_distro,
            name=selected_name,
            username=username,
            profile=profile,
            desktop=desktop,
            release=release,
            version=version,
        )

    def list_versions(self, *, distro: str, name: str | None = None, username: str | None = None) -> list[ReleaseRef]:
        config_name = name or distro
        runtime = self.services.runtime_for(config_name, username=username or self.services.base_config.username)
        installer = build_installer(
            distro,
            runtime.config,
            runtime.runner,
            runtime.controller,
            self.services.registry,
            runtime.user_sync,
            self.services.logger,
        )
        return installer.list_versions()

    def install(
        self,
        request: InstallRequest,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> InstallRunResult:
        runtime = self.services.runtime_for(request.name, username=request.username)
        installer = build_installer(
            request.distro,
            runtime.config,
            runtime.runner,
            runtime.controller,
            self.services.registry,
            runtime.user_sync,
            self.services.logger,
        )
        phase_results = []
        if progress is not None:
            progress("Preparing install")
        for item in installer.install(
            phase=request.phase,
            username=request.username,
            desktop=request.desktop,
            version=request.version,
            release=request.release,
            force_phase=request.force_phase,
            auto=False,
            resume=request.resume,
            repair=request.repair,
            profile=request.profile,
        ):
            phase_results.append(item)
            phase_name = str(getattr(item, "phase", "install"))
            if progress is not None:
                progress(f"Completed phase: {phase_name}")
        tool_results = []
        addon_results = []
        record = self.services.registry.get(request.name)
        if (request.tools or request.addons) and (record is None or not bool(record.get("installed"))):
            raise RuntimeError("tools and addons can only be applied after finalize completes")
        if request.tools:
            tool_results = self.services.catalog("tool", name=request.name).apply(list(request.tools), progress=progress)
        if request.addons:
            addon_results = self.services.catalog("addon", name=request.name).apply(list(request.addons), progress=progress)
        next_steps = tuple(_install_next_steps(request.name, username=request.username))
        if progress is not None:
            progress("Install completed")
        return InstallRunResult(
            chroot_name=request.name,
            distro=request.distro,
            phases=tuple(phase_results),
            tool_results=tuple(tool_results),
            addon_results=tuple(addon_results),
            next_steps=next_steps,
        )

    def upgrade(
        self,
        name: str,
        *,
        username: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> UpgradeResult:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"no registry record for chroot: {name}")
        target_username = username or _default_username_hint(self.services, name) or self.services.base_config.username
        if not target_username:
            raise RuntimeError("upgrade requires a username")
        runtime = self.services.runtime_for(name, username=target_username)
        installer = build_installer(
            str(record.get("distro") or ""),
            runtime.config,
            runtime.runner,
            runtime.controller,
            self.services.registry,
            runtime.user_sync,
            self.services.logger,
        )
        if progress is not None:
            progress("Upgrading chroot")
        result = installer.upgrade()
        if progress is not None:
            progress("Upgrade completed")
        return UpgradeResult(
            status=result.status,
            snapshot=result.snapshot,
            next_steps=(
                f"chrootctl --name {name} restart",
                f"chrootctl --name {name} logs --all",
            ),
        )


def _preferred_record(services: ServiceContainer, *, name: str | None = None, distro: str | None = None):
    if name:
        record = services.registry.get(name)
        if record is not None:
            return record
    rows = list(services.registry.list())
    incomplete = [row for row in rows if not bool(row.get("installed"))]
    if len(incomplete) == 1:
        return services.registry.get(str(incomplete[0]["name"]))
    if distro is not None:
        matches = [row for row in rows if str(row.get("distro", "")) == distro]
        if len(matches) == 1:
            return services.registry.get(str(matches[0]["name"]))
    if len(rows) == 1:
        return services.registry.get(str(rows[0]["name"]))
    return None


def _metadata_value(metadata: object, key: str) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validated_username(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_username(value)
    except ValueError:
        return None


def _default_username_hint(services: ServiceContainer, chroot_name: str | None) -> str | None:
    runtime = services.runtime_for(chroot_name)
    existing = [row.username for row in runtime.chroot_users.user_rows() if row.username != "root" and str(getattr(row, "uid", "")) != "0"]
    if len(existing) == 1:
        return existing[0]
    env_user = os.environ.get("USER", "").strip()
    if env_user and env_user != "root":
        try:
            return validate_username(env_user)
        except ValueError:
            return None
    configured = services.base_config.username
    if configured and configured != "root" and configured != "mike":
        try:
            return validate_username(configured)
        except ValueError:
            return None
    return None


def _install_next_steps(name: str, *, username: str) -> list[str]:
    return [
        f"chrootctl --name {name} start",
        f"chrootctl --name {name} users sync-id {username}",
        f"chrootctl --name {name} logs --all",
    ]
