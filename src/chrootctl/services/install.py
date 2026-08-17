from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import replace
from typing import Any
from pathlib import Path

from ..base_install import ReleaseRef
from ..installer_factory import build_installer
from ..models import InstallRequest, InstallWizardDefaults
from ..user_sync import validate_username
from ..validation import validate_chroot_name
from .context import ServiceContainer
from .install_execution import InstallExecutionService

PROFILE_OPTIONS = ("minimal", "dev", "xfce4", "plasma", "custom")
DESKTOP_OPTIONS = ("auto", "none", "xfce4", "plasma")
DISTRO_OPTIONS = ("ubuntu", "arch")
ARCH_OPTIONS = ("arm64", "amd64")
COMPATIBILITY_MATRIX = {
    "ubuntu": {
        "releases": ("noble", "jammy"),
        "arches": ("arm64", "amd64"),
        "profiles": ("minimal", "dev", "xfce4", "plasma", "custom"),
        "desktops": {
            "minimal": ("none",),
            "dev": ("none",),
            "xfce4": ("auto", "xfce4", "none"),
            "plasma": ("auto", "plasma", "none"),
            "custom": ("none", "xfce4", "plasma"),
        },
    },
    "arch": {
        "releases": ("rolling",),
        "arches": ("arm64",),
        "profiles": ("minimal", "dev", "xfce4", "plasma", "custom"),
        "desktops": {
            "minimal": ("none",),
            "dev": ("none",),
            "xfce4": ("auto", "xfce4", "none"),
            "plasma": ("auto", "plasma", "none"),
            "custom": ("none", "xfce4", "plasma"),
        },
    },
}

INSTALL_PRESETS = {
    "minimal-server": {
        "id": "minimal-server",
        "label": "Minimal server",
        "description": "Minimal shell-first install with no desktop.",
        "profile": "minimal",
        "desktop": "none",
        "tools": (),
        "addons": (),
    },
    "desktop-xfce": {
        "id": "desktop-xfce",
        "label": "Desktop XFCE",
        "description": "Light desktop preset for interactive use.",
        "profile": "xfce4",
        "desktop": "xfce4",
        "tools": (),
        "addons": (),
    },
    "development": {
        "id": "development",
        "label": "Development",
        "description": "Developer-focused base with non-desktop defaults.",
        "profile": "dev",
        "desktop": "none",
        "tools": ("sync-uid",),
        "addons": (),
    },
    "recovery-debug": {
        "id": "recovery-debug",
        "label": "Recovery/debug",
        "description": "Conservative preset for repairs and diagnostics.",
        "profile": "custom",
        "desktop": "none",
        "tools": (),
        "addons": (),
    },
}

UBUNTU_RELEASE_VERSION_PREFIX = {"jammy": "22.04", "noble": "24.04"}

MIRROR_OPTIONS = {
    "ubuntu": (
        {"id": "auto", "label": "Auto-select", "url": "", "healthy": True, "arches": ("arm64", "amd64")},
        {"id": "archive.ubuntu.com", "label": "Ubuntu archive (amd64)", "url": "https://archive.ubuntu.com/ubuntu", "healthy": True, "arches": ("amd64",)},
        {"id": "ports.ubuntu.com", "label": "Ubuntu ports (arm64)", "url": "https://ports.ubuntu.com/ubuntu-ports", "healthy": True, "arches": ("arm64",)},
    ),
    "arch": (
        {"id": "auto", "label": "Arch Linux ARM Geo mirror", "url": "", "healthy": True, "arches": ("arm64",)},
        {"id": "mirror.archlinuxarm.org", "label": "Arch Linux ARM Geo mirror", "url": "https://mirror.archlinuxarm.org", "healthy": True, "arches": ("arm64",)},
    ),
}


INSTALL_STEPS = (
    {
        "id": "validate",
        "label": "Validate request",
        "description": "Check distro, profile, username, and desktop rules before any filesystem changes.",
    },
    {
        "id": "extract",
        "label": "Extract base system",
        "description": "Download or locate the base rootfs and extract it into the chroot directory.",
    },
    {
        "id": "bootstrap",
        "label": "Bootstrap packages and user",
        "description": "Mount runtime filesystems, configure networking, install base packages, and create the user.",
    },
    {
        "id": "desktop",
        "label": "Desktop package pass",
        "description": "Install no desktop for minimal/dev profiles, or lightweight desktop packages when requested.",
    },
    {
        "id": "finalize",
        "label": "Finalize install",
        "description": "Run post-install hooks, sync metadata, and mark the chroot installed.",
    },
    {
        "id": "catalog",
        "label": "Apply selected tools/addons",
        "description": "Apply optional tools and addons only after finalize succeeds.",
    },
)


class InstallService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def distros(self) -> tuple[str, ...]:
        return DISTRO_OPTIONS

    def profiles(self) -> tuple[str, ...]:
        return PROFILE_OPTIONS

    def desktops(self) -> tuple[str, ...]:
        return DESKTOP_OPTIONS

    def mirror_options(self, distro: str | None = None, arch: str | None = None) -> list[dict[str, object]]:
        selected = (distro or DISTRO_OPTIONS[0]).strip() or DISTRO_OPTIONS[0]
        if selected not in MIRROR_OPTIONS:
            raise ValueError(f"unsupported distro: {selected}")
        target_arch = (arch or "").strip().lower()
        options: list[dict[str, object]] = []
        for raw in MIRROR_OPTIONS[selected]:
            item = dict(raw)
            supported = tuple(str(value) for value in item.get("arches", ()))
            if target_arch and supported and target_arch not in supported:
                continue
            options.append(item)
        if target_arch and not options:
            raise ValueError(f"{selected} has no configured mirrors for target architecture {target_arch}")
        return options


    def _resolved_request_username(self, request: InstallRequest) -> str:
        candidate = (request.username or "").strip()
        if candidate:
            return validate_username(candidate)
        defaults = self.wizard_defaults(name=request.name, distro=request.distro)
        fallback = (defaults.username or "").strip() or _default_username_hint(self.services, request.name)
        if not fallback:
            raise ValueError("install username is required; choose a target user")
        return validate_username(fallback)

    def storage_status(self, *, name: str | None = None) -> dict[str, Any]:
        config = self.services.config if name is None else self.services.config_for(name)
        target = Path(config.chroot_root).expanduser()
        probe = target
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if not probe.exists():
            raise RuntimeError(f"cannot determine storage capacity for {target}")
        usage = shutil.disk_usage(probe)
        return {
            "path": str(target),
            "free_bytes": int(usage.free),
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
        }

    def preview_install(self, request: InstallRequest) -> dict[str, Any]:
        result = self.validate_install_submission(request)
        if not result.get("ok"):
            return result
        plan = result.get("plan") or {}
        resolved_username = str(plan.get("username") or request.username or "")
        distro = str(plan.get("distro") or request.distro)
        arch = str(plan.get("arch") or request.arch)
        mirror_info = _resolve_mirror(self.mirror_options(distro, arch), request.mirror)
        storage = self.storage_status(name=request.name)
        estimate = _install_estimate(request)
        enough_space = storage["free_bytes"] >= estimate["required_bytes"]
        install_command = [
            "chrootctl", "install", distro, "--name", request.name, "--username", resolved_username,
            "--arch", arch, "--phase", request.phase or "extract", "--dry-run",
        ]
        if request.release:
            install_command.extend(["--release", request.release])
        if request.version:
            install_command.extend(["--version", request.version])
        preview = {
            "storage": {
                **storage,
                **estimate,
                "enough_space": enough_space,
            },
            "mirror": mirror_info,
            "dry_run": {
                "supported": True,
                "install": shlex.join(install_command),
                "export": shlex.join(["chrootctl", "--name", request.name, "transfer", "export", "./archive.tar.zst", "--dry-run"]),
                "import": "chrootctl transfer import ./archive.tar.zst --dry-run",
            },
        }
        result["preview"] = preview
        result.setdefault("warnings", [])
        if not enough_space:
            result["ok"] = False
            result.setdefault("blocking", []).append(_blocking_issue(
                code="insufficient_storage",
                message=f"Not enough free space for the requested install. Need about {estimate['required_bytes']//(1024*1024)} MiB but only {storage['free_bytes']//(1024*1024)} MiB is free.",
                fix_label="Open dashboard",
                fix_href="/",
            ))
        if mirror_info["selection"] == "auto" and len(mirror_info["fallback_chain"]) > 1:
            result["resolved"].append(f"Mirror will auto-fallback through {', '.join(mirror_info['fallback_chain'])}.")
        return result


    def preset_options(self, distro: str | None = None) -> list[dict[str, object]]:
        supported_profiles = set(COMPATIBILITY_MATRIX.get(distro or "ubuntu", COMPATIBILITY_MATRIX["ubuntu"])["profiles"])
        result: list[dict[str, object]] = []
        for preset in INSTALL_PRESETS.values():
            if str(preset["profile"]) not in supported_profiles:
                continue
            result.append(dict(preset))
        return result

    def compatibility_matrix(self, distro: str | None = None) -> dict[str, object]:
        selected = distro or "ubuntu"
        matrix = COMPATIBILITY_MATRIX.get(selected, COMPATIBILITY_MATRIX["ubuntu"])
        return {
            "distro": selected,
            "releases": list(matrix["releases"]),
            "arches": list(matrix["arches"]),
            "profiles": list(matrix["profiles"]),
            "desktops": {key: list(value) for key, value in matrix["desktops"].items()},
        }

    def apply_preset(self, request: InstallRequest) -> InstallRequest:
        preset_id = (request.preset or "").strip()
        if not preset_id:
            return request
        preset = INSTALL_PRESETS.get(preset_id)
        if preset is None:
            raise ValueError(f"unknown install preset: {preset_id}")
        tools = request.tools or tuple(preset.get("tools", ()))
        addons = request.addons or tuple(preset.get("addons", ()))
        return InstallRequest(
            distro=request.distro,
            name=request.name,
            username=request.username,
            arch=request.arch,
            preset=preset_id,
            profile=request.profile or str(preset.get("profile") or "") or None,
            desktop=request.desktop or str(preset.get("desktop") or "") or None,
            release=request.release,
            version=request.version,
            mirror=request.mirror,
            phase=request.phase,
            force_phase=request.force_phase,
            resume=request.resume,
            repair=request.repair,
            tools=tuple(tools),
            addons=tuple(addons),
        )

    def profile_options(self) -> list[dict[str, object]]:
        return [
            {
                "id": profile,
                "label": _profile_label(profile),
                "desktop_allowed": profile not in {"minimal", "dev"},
                "default_desktop": "none" if profile in {"minimal", "dev", "custom"} else profile,
                "description": _profile_description(profile),
            }
            for profile in PROFILE_OPTIONS
        ]

    def desktop_options(self) -> list[dict[str, object]]:
        return [
            {
                "id": desktop,
                "label": _desktop_label(desktop),
                "lightweight": desktop in {"xfce4", "plasma"},
                "packages": _desktop_package_preview(desktop),
            }
            for desktop in DESKTOP_OPTIONS
        ]


    def list_target_users(self, *, name: str | None = None) -> list[dict[str, str]]:
        try:
            runtime = self.services.runtime_for(name)
            rows = runtime.chroot_users.user_rows()
        except Exception:
            return []
        users: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in rows:
            username = str(getattr(row, "username", "")).strip()
            uid = str(getattr(row, "uid", "")).strip()
            if not username or username == "root" or uid == "0" or username in seen:
                continue
            users.append(
                {
                    "username": username,
                    "uid": uid or "unknown",
                    "gid": str(getattr(row, "gid", "")).strip() or "unknown",
                    "home": str(getattr(row, "home", "")).strip() or f"/home/{username}",
                    "shell": str(getattr(row, "shell", "")).strip() or "/bin/bash",
                }
            )
            seen.add(username)
        return users

    def install_form_state(self, *, name: str | None = None, distro: str | None = None) -> dict[str, Any]:
        defaults = self.wizard_defaults(name=name, distro=distro)
        selected_distro = distro or defaults.distro or "ubuntu"
        users = self.list_target_users(name=name or defaults.name)
        return {
            "defaults": {
                "distro": defaults.distro or selected_distro,
                "name": defaults.name,
                "username": defaults.username,
                "arch": getattr(self.services.config_for(name or defaults.name), "target_arch", "arm64"),
                "preset": defaults.preset or "minimal-server",
                "profile": defaults.profile or "minimal",
                "desktop": defaults.desktop or "none",
                "release": defaults.release,
                "version": defaults.version,
            },
            "distros": [{"id": distro_id, "label": distro_id.title()} for distro_id in self.distros()],
            "architectures": [{"id": arch, "label": arch} for arch in ARCH_OPTIONS],
            "profiles": self.profile_options(),
            "desktops": self.desktop_options(),
            "presets": self.preset_options(selected_distro),
            "compatibility": self.compatibility_matrix(selected_distro),
            "mirrors": self.mirror_options(selected_distro),
            "users": users,
            "requirements": {
                "username_required": True,
                "root_required": True,
            },
            "rules": {
                "minimal_forces_desktop": "none",
                "minimal_rejects_desktop": True,
                "ubuntu_desktop_packages": "lightweight-no-recommends",
            },
        }

    def validate_install_submission(self, request: InstallRequest) -> dict[str, Any]:
        blocking: list[dict[str, Any]] = []
        users: list[dict[str, str]] = []
        username_was_explicit = bool((request.username or "").strip())
        try:
            request = self.apply_preset(request)
            validate_chroot_name(request.name, field="install name")
            if request.distro not in DISTRO_OPTIONS:
                raise ValueError(f"unsupported distro: {request.distro}")
            users = self.list_target_users(name=request.name)
            resolved_username = self._resolved_request_username(request)
        except ValueError as exc:
            blocking.append(_map_install_error(str(exc)))
            return {
                "ok": False,
                "blocking": blocking,
                "warnings": [],
                "resolved": [],
                "plan": None,
                "users": users,
                "requirements": {"username_required": True, "default_username": ""},
            }

        normalized_username = resolved_username
        matrix = self.compatibility_matrix(request.distro)
        profile_id = (request.profile or "minimal").strip()
        desktop_id = (request.desktop or "auto").strip()
        if profile_id not in set(matrix["profiles"]):
            blocking.append(_blocking_issue(code="invalid_profile", message=f"Profile '{profile_id}' is not supported for {request.distro}.", fix_label="Choose supported profile", fix_href="/install"))
        elif desktop_id not in set(matrix["desktops"].get(profile_id, [])):
            blocking.append(_blocking_issue(code="invalid_profile_desktop_combo", message=f"Profile '{profile_id}' cannot use desktop '{desktop_id}'.", fix_label="Switch desktop", fix_href="/install"))
        if blocking:
            return {
                "ok": False,
                "blocking": blocking,
                "warnings": [],
                "resolved": [],
                "plan": None,
                "users": users,
                "requirements": {"username_required": True, "default_username": normalized_username},
            }

        try:
            request = replace(request, username=resolved_username)
            plan = self.validate_install_request(request)
            if request.preset:
                plan["preset"] = request.preset
            mirror_info = _resolve_mirror(self.mirror_options(request.distro, request.arch), request.mirror)
            plan["mirror"] = mirror_info["selected_url"] or mirror_info["selection"]
            plan["mirror_fallback_chain"] = mirror_info["fallback_chain"]
        except ValueError as exc:
            blocking.append(_map_install_error(str(exc)))
            return {
                "ok": False,
                "blocking": blocking,
                "warnings": [],
                "resolved": [],
                "plan": None,
                "users": users,
                "requirements": {"username_required": True, "default_username": normalized_username},
            }

        resolved: list[str] = []
        requested_desktop = plan.get("requested_desktop")
        resolved_desktop = plan.get("desktop")
        if requested_desktop and resolved_desktop and requested_desktop != resolved_desktop:
            resolved.append(f"Desktop changed from {requested_desktop} → {resolved_desktop}.")
        if not username_was_explicit:
            resolved.append(f"Using discovered target user {normalized_username}.")
        if users and normalized_username not in {item["username"] for item in users}:
            resolved.append(f"Target user {normalized_username} will be created during install.")
        elif not users:
            resolved.append(f"Target user {normalized_username} will be created during install.")
        return {
            "ok": True,
            "blocking": [],
            "warnings": list(plan.get("warnings", ())),
            "resolved": resolved,
            "plan": plan,
            "users": users,
            "requirements": {"username_required": True, "default_username": normalized_username},
        }

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
        if (profile or "minimal") == "minimal":
            desktop = "none"
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

    def install_feedback_plan(self, request: InstallRequest) -> dict[str, Any]:
        profile = (request.profile or "minimal").strip() or "minimal"
        requested_desktop = (request.desktop or "auto").strip() or "auto"
        resolved_desktop = "none"
        if profile == "minimal":
            if requested_desktop not in {"auto", "none"}:
                raise ValueError("minimal profile does not allow desktop installation; choose profile xfce4/plasma or desktop none")
        elif requested_desktop == "auto":
            resolved_desktop = next(
                (
                    str(item["default_desktop"])
                    for item in self.profile_options()
                    if item["id"] == profile
                ),
                "none",
            )
        else:
            resolved_desktop = requested_desktop
        selected_steps = [dict(step) for step in INSTALL_STEPS]
        if not request.tools and not request.addons:
            selected_steps = [step for step in selected_steps if step["id"] != "catalog"]
        return {
            "name": request.name,
            "distro": request.distro,
            "username": request.username,
            "arch": request.arch,
            "profile": profile,
            "requested_desktop": requested_desktop,
            "desktop": resolved_desktop,
            "release": request.release or "auto",
            "version": request.version or "latest",
            "mirror": request.mirror or "auto",
            "tools": list(request.tools),
            "addons": list(request.addons),
            "repair": request.repair,
            "steps": selected_steps,
            "total_steps": len(selected_steps),
            "warnings": _install_plan_warnings(profile=profile, desktop=resolved_desktop, tools=request.tools, addons=request.addons),
        }

    def validate_install_request(self, request: InstallRequest) -> dict[str, Any]:
        validate_chroot_name(request.name, field="install name")
        validate_username(request.username)
        if request.distro not in DISTRO_OPTIONS:
            raise ValueError(f"unsupported distro: {request.distro}")
        matrix = COMPATIBILITY_MATRIX[request.distro]
        arch = (request.arch or "").strip().lower()
        if arch not in ARCH_OPTIONS:
            raise ValueError(f"unsupported target architecture: {arch}")
        if arch not in set(matrix["arches"]):
            raise ValueError(f"{request.distro} does not support target architecture {arch}")
        profile = request.profile or "minimal"
        if profile not in PROFILE_OPTIONS or profile not in set(matrix["profiles"]):
            raise ValueError(f"unsupported profile: {request.profile}")
        desktop = (request.desktop or "auto").strip() or "auto"
        if desktop not in DESKTOP_OPTIONS:
            raise ValueError(f"unsupported desktop: {desktop}")
        if request.release and request.release not in set(matrix["releases"]):
            raise ValueError(f"unsupported {request.distro} release: {request.release}")
        version = (request.version or "").strip()
        if version:
            if request.distro == "ubuntu":
                if not re.fullmatch(r"\d{2}\.\d{2}(?:\.\d+)?", version):
                    raise ValueError(f"unsupported ubuntu version: {version}")
                allowed_prefixes = set(UBUNTU_RELEASE_VERSION_PREFIX.values())
                if not any(version == prefix or version.startswith(prefix + ".") for prefix in allowed_prefixes):
                    raise ValueError(f"unsupported ubuntu version: {version}")
                if request.release:
                    prefix = UBUNTU_RELEASE_VERSION_PREFIX[request.release]
                    if version != prefix and not version.startswith(prefix + "."):
                        raise ValueError(f"ubuntu release {request.release} is incompatible with version {version}")
            elif request.distro == "arch" and version != "latest":
                raise ValueError("Arch Linux ARM uses the rolling 'latest' bootstrap version")
        if request.phase and request.phase not in {"extract", "bootstrap", "desktop", "finalize"}:
            raise ValueError(f"unsupported install phase: {request.phase}")
        if request.resume and request.repair:
            raise ValueError("resume and repair are mutually exclusive install modes")
        if request.phase and (request.resume or request.repair):
            raise ValueError("explicit phase cannot be combined with resume/repair")
        if request.force_phase and request.phase is None:
            raise ValueError("force_phase requires an explicit phase")
        if request.force_phase and (request.resume or request.repair):
            raise ValueError("force_phase cannot be combined with resume/repair")
        _resolve_mirror(self.mirror_options(request.distro, arch), request.mirror)
        return self.install_feedback_plan(request)

    def _execution(self) -> InstallExecutionService:
        return InstallExecutionService(
            self.services,
            apply_preset=self.apply_preset,
            resolve_username=self._resolved_request_username,
            validate_install_request=self.validate_install_request,
            mirror_options=self.mirror_options,
            resolve_mirror=_resolve_mirror,
            install_next_steps=_install_next_steps,
            build_installer_fn=build_installer,
        )

    def list_versions(self, *, distro: str, name: str | None = None, username: str | None = None) -> list[ReleaseRef]:
        return self._execution().list_versions(distro=distro, name=name, username=username)

    def install(self, request: InstallRequest, *, progress=None):
        return self._execution().install(request, progress=progress)

    def upgrade(self, name: str, *, username: str | None = None, progress=None):
        return self._execution().upgrade(name, username=username, progress=progress)


def _blocking_issue(
    *,
    code: str,
    message: str,
    fix_label: str | None = None,
    fix_href: str | None = None,
    secondary_label: str | None = None,
    secondary_href: str | None = None,
) -> dict[str, Any]:
    issue = {
        "code": code,
        "message": message,
    }
    actions: list[dict[str, str]] = []
    if fix_label and fix_href:
        actions.append({"label": fix_label, "href": fix_href})
    if secondary_label and secondary_href:
        actions.append({"label": secondary_label, "href": secondary_href})
    if actions:
        issue["actions"] = actions
    return issue


def _map_install_error(message: str) -> dict[str, Any]:
    lowered = message.lower()
    if "no non-root users available" in lowered or "username" in lowered:
        return _blocking_issue(
            code="missing_username",
            message="No non-root users are available. Choose or create a user before installing this chroot.",
            fix_label="Create user",
            fix_href="/install#target-user-step",
            secondary_label="Use advanced install with --username",
            secondary_href="/install#target-user-step",
        )
    if "dependency" in lowered or "missing deps" in lowered:
        return _blocking_issue(
            code="missing_dependency",
            message="Python dependency missing. Open module status or review the suggested fix command before retrying.",
            fix_label="Open module status",
            fix_href="/ksu",
            secondary_label="Open checks",
            secondary_href="/doctor",
        )
    if "minimal profile does not allow desktop" in lowered:
        return _blocking_issue(
            code="desktop_profile_conflict",
            message="Minimal profile cannot install a desktop. Switch to XFCE/Plasma or keep desktop set to none.",
            fix_label="Switch profile",
            fix_href="/install#profile-step",
            secondary_label="Keep minimal",
            secondary_href="/install#profile-step",
        )
    return _blocking_issue(code="invalid_request", message=message)



def _install_plan_warnings(*, profile: str, desktop: str, tools: tuple[str, ...], addons: tuple[str, ...]) -> list[str]:
    warnings: list[str] = []
    if profile == "minimal" and desktop == "none":
        warnings.append("Minimal profile will skip desktop package installation.")
    if desktop in {"xfce4", "plasma"}:
        warnings.append("Desktop installation uses lightweight packages with --no-install-recommends.")
    if tools or addons:
        warnings.append("Tools and addons run after finalize; failures there do not mean base extraction failed.")
    return warnings

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
    try:
        runtime = services.runtime_for(chroot_name)
        existing = [row.username for row in runtime.chroot_users.user_rows() if row.username != "root" and str(getattr(row, "uid", "")) != "0"]
    except Exception:
        existing = []
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

def _profile_label(profile: str) -> str:
    labels = {
        "minimal": "Minimal",
        "dev": "Developer",
        "xfce4": "XFCE Desktop",
        "plasma": "KDE Plasma Desktop",
        "custom": "Custom",
    }
    return labels.get(profile, profile.replace("_", " ").replace("-", " ").title())


def _profile_description(profile: str) -> str:
    descriptions = {
        "minimal": "Base system only. No desktop environment is installed.",
        "dev": "Developer-focused base image with CLI tooling and no desktop.",
        "xfce4": "Balanced desktop profile with XFCE packages preselected.",
        "plasma": "Full desktop profile with KDE Plasma packages preselected.",
        "custom": "Start from a minimal base and choose packages manually.",
    }
    return descriptions.get(profile, "Install profile.")


def _desktop_label(desktop: str) -> str:
    labels = {
        "auto": "Automatic",
        "none": "None",
        "xfce4": "XFCE",
        "plasma": "KDE Plasma",
    }
    return labels.get(desktop, desktop.replace("_", " ").replace("-", " ").title())


def _desktop_package_preview(desktop: str) -> str:
    previews = {
        "auto": "Installer chooses the best desktop for the selected profile.",
        "none": "Base system only.",
        "xfce4": "xfce4, xfce4-goodies, xorg",
        "plasma": "plasma-desktop, sddm, xorg",
    }
    return previews.get(desktop, "Desktop packages selected by installer.")


def _resolve_mirror(options: list[dict[str, object]], requested: str | None) -> dict[str, Any]:
    normalized = (requested or "auto").strip() or "auto"
    selected = next((item for item in options if str(item.get("id")) == normalized), None)
    if selected is None:
        allowed = ", ".join(str(item.get("id")) for item in options) or "(none)"
        raise ValueError(f"unknown mirror '{normalized}'; choose one of: {allowed}")
    healthy = [str(item.get("id")) for item in options if bool(item.get("healthy", True)) and str(item.get("id")) != "auto"]
    fallback_chain = healthy or [str(selected.get("id", normalized))]
    return {
        "selection": normalized,
        "selected_label": str(selected.get("label", normalized)),
        "selected_url": str(selected.get("url", "")),
        "healthy": bool(selected.get("healthy", True)),
        "fallback_chain": fallback_chain,
    }


def _install_estimate(request: InstallRequest) -> dict[str, int]:
    profile = (request.profile or "minimal").strip() or "minimal"
    base_download = 350 * 1024 * 1024
    base_install = 1200 * 1024 * 1024
    if profile == "dev":
        base_download += 180 * 1024 * 1024
        base_install += 700 * 1024 * 1024
    if profile in {"xfce4", "plasma"} or (request.desktop or "") in {"xfce4", "plasma"}:
        base_download += 650 * 1024 * 1024
        base_install += 2200 * 1024 * 1024
    base_download += (len(request.tools) + len(request.addons)) * 40 * 1024 * 1024
    base_install += (len(request.tools) + len(request.addons)) * 150 * 1024 * 1024
    return {
        "download_bytes": int(base_download),
        "required_bytes": int(base_install),
        "estimated_seconds": int(max(120, base_download // (6 * 1024 * 1024))),
    }
