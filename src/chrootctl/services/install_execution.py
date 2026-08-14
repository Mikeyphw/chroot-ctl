from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..models import InstallRequest, InstallRunResult, UpgradeResult
from .context import ServiceContainer


class InstallExecutionService:
    def __init__(
        self,
        services: ServiceContainer,
        *,
        apply_preset,
        resolve_username,
        validate_install_request,
        mirror_options,
        resolve_mirror,
        install_next_steps,
        build_installer_fn,
    ) -> None:
        self.services = services
        self._apply_preset = apply_preset
        self._resolve_username = resolve_username
        self._validate_install_request = validate_install_request
        self._mirror_options = mirror_options
        self._resolve_mirror = resolve_mirror
        self._install_next_steps = install_next_steps
        self._build_installer_fn = build_installer_fn

    def list_versions(self, *, distro: str, name: str | None = None, username: str | None = None):
        config_name = name or distro
        runtime = self.services.runtime_for(config_name, username=username or self.services.base_config.username)
        installer = self._build_installer_fn(
            distro,
            config=runtime.config,
            runner=runtime.runner,
            controller=runtime.controller,
            registry=self.services.registry,
            user_sync=runtime.user_sync,
            logger=self.services.logger,
        )
        return installer.list_versions()

    def _build_installer_for_attempt(
        self,
        *,
        distro: str,
        name: str,
        username: str,
        arch: str,
        mirror_selection: str,
        base_url: str | None,
        mirror_candidates: list[dict[str, object]],
    ):
        runtime = self.services.runtime_for(name, username=username)
        runtime_config = runtime.config.with_overrides(target_arch=arch)
        installer = self._build_installer_fn(
            distro,
            config=runtime_config,
            runner=runtime.runner,
            controller=runtime.controller,
            registry=self.services.registry,
            user_sync=runtime.user_sync,
            logger=self.services.logger,
        )
        configure_mirror = getattr(installer, "configure_mirror_plan", None)
        if callable(configure_mirror):
            configure_mirror(
                selection=mirror_selection,
                base_url=base_url,
                candidates=[
                    {"id": str(item.get("id", "")), "url": str(item.get("url", ""))}
                    for item in mirror_candidates
                    if str(item.get("id", "")) != "auto" and str(item.get("url", "")).strip()
                ],
            )
        return installer

    def _mirror_attempts(self, mirror_options: list[dict[str, object]], mirror_info: dict[str, Any]) -> list[dict[str, str | None]]:
        selected_url = str(mirror_info.get("selected_url") or "").strip() or None
        attempts: list[dict[str, str | None]] = [
            {
                "selection": str(mirror_info.get("selection", "auto")) or "auto",
                "base_url": selected_url,
                "label": str(mirror_info.get("selection", "auto")) or "auto",
            }
        ]
        seen = {(attempts[0]["selection"], attempts[0]["base_url"])}
        for item in mirror_options:
            mirror_id = str(item.get("id", "")).strip()
            mirror_url = str(item.get("url", "")).strip() or None
            if not mirror_id or mirror_id == "auto":
                continue
            key = (mirror_id, mirror_url)
            if key in seen:
                continue
            attempts.append({"selection": mirror_id, "base_url": mirror_url, "label": mirror_id})
            seen.add(key)
        return attempts

    def install(
        self,
        request: InstallRequest,
        *,
        progress: Callable[[Any], None] | None = None,
    ) -> InstallRunResult:
        request = self._apply_preset(request)
        request = replace(request, username=self._resolve_username(request))
        plan = self._validate_install_request(request)
        mirror_options = self._mirror_options(request.distro, request.arch)
        mirror_info = self._resolve_mirror(mirror_options, request.mirror)
        plan["mirror"] = mirror_info["selected_url"] or mirror_info["selection"]
        plan["mirror_fallback_chain"] = mirror_info["fallback_chain"]
        plan["mirror_attempts"] = [str(item.get("id", "")) for item in mirror_options if str(item.get("id", "")).strip() and str(item.get("id", "")) != "auto"]

        if progress is not None:
            progress({
                "phase": "validate",
                "message": "Install request validated",
                "percent": 8,
                "plan": plan,
                "current_step": 1,
                "total_steps": plan["total_steps"],
            })

        phase_results = []
        phase_index = {"extract": 2, "bootstrap": 3, "desktop": 4, "finalize": 5}
        mirror_attempt_errors: list[dict[str, str]] = []
        install_attempts = self._mirror_attempts(mirror_options, mirror_info)

        def _run_attempt(installer, attempt_label: str) -> list[Any]:
            if progress is not None:
                progress({
                    "phase": "extract",
                    "message": f"Running install phases via {attempt_label}",
                    "percent": 12,
                    "plan": plan,
                    "current_step": 2,
                    "total_steps": plan["total_steps"],
                })
            results = []
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
                results.append(item)
                phase_name = str(getattr(item, "phase", "install"))
                if progress is not None:
                    step_number = min(phase_index.get(phase_name, len(results) + 1), plan["total_steps"])
                    progress({
                        "phase": phase_name,
                        "message": f"Completed phase: {phase_name}",
                        "percent": min(92, int((step_number / max(plan["total_steps"], 1)) * 92)),
                        "plan": plan,
                        "current_step": step_number,
                        "total_steps": plan["total_steps"],
                        "result": item,
                    })
            return results

        # Rootfs verification and package-source fallback happen inside the installer.
        # A bootstrap/desktop/finalize failure must never replay earlier phases.
        attempt = install_attempts[0]
        installer = self._build_installer_for_attempt(
            distro=request.distro,
            name=request.name,
            username=request.username,
            arch=request.arch,
            mirror_selection=str(attempt["selection"] or "auto"),
            base_url=str(attempt["base_url"]) if attempt["base_url"] else None,
            mirror_candidates=mirror_options,
        )
        phase_results = _run_attempt(installer, str(attempt["label"] or "auto"))
        plan["mirror_retry_count"] = 0

        tool_results = []
        addon_results = []
        record = self.services.registry.get(request.name)
        if (request.tools or request.addons) and (record is None or not bool(record.get("installed"))):
            raise RuntimeError("tools and addons can only be applied after finalize completes")
        if (request.tools or request.addons) and progress is not None:
            progress({
                "phase": "catalog",
                "message": "Applying selected tools and addons",
                "percent": 94,
                "plan": plan,
                "current_step": plan["total_steps"],
                "total_steps": plan["total_steps"],
            })
        if request.tools:
            tool_results = self.services.catalog("tool", name=request.name).apply(list(request.tools), progress=progress)
        if request.addons:
            addon_results = self.services.catalog("addon", name=request.name).apply(list(request.addons), progress=progress)
        next_steps = tuple(self._install_next_steps(request.name, username=request.username))
        if progress is not None:
            progress({
                "phase": "complete",
                "message": "Install completed",
                "percent": 100,
                "plan": plan,
                "current_step": plan["total_steps"],
                "total_steps": plan["total_steps"],
                "mirror_errors": mirror_attempt_errors,
            })
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
        progress: Callable[[Any], None] | None = None,
    ) -> UpgradeResult:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"no registry record for chroot: {name}")
        target_username = username or self.services.base_config.username
        if not target_username:
            raise RuntimeError("upgrade requires a username")
        runtime = self.services.runtime_for(name, username=target_username)
        installer = self._build_installer_fn(
            str(record.get("distro") or ""),
            config=runtime.config,
            runner=runtime.runner,
            controller=runtime.controller,
            registry=self.services.registry,
            user_sync=runtime.user_sync,
            logger=self.services.logger,
        )
        if progress is not None:
            progress({"phase": "upgrade", "percent": 25, "message": "Upgrading chroot"})
        result = installer.upgrade()
        if progress is not None:
            progress({"phase": "upgrade", "percent": 95, "message": "Upgrade completed"})
        return UpgradeResult(
            status=result.status,
            snapshot=result.snapshot,
            next_steps=(
                f"chrootctl --name {name} restart",
                f"chrootctl --name {name} logs --all",
            ),
        )
