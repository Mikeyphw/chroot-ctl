from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..catalog import ManifestCatalog
from ..models import CatalogApplyResult
from .context import ServiceContainer


class CatalogService:
    def __init__(self, services: ServiceContainer, *, kind: str, chroot_name: str | None = None) -> None:
        self.services = services
        self.kind = kind
        self.chroot_name = chroot_name

    def _catalog(self):
        config = self.services.config_for(self.chroot_name)
        return ManifestCatalog(self.kind, config=config)

    def list_entries(self, *, distro: str | None = None, category: str | None = None):
        return self._catalog().list_entries(distro=distro, category=category)

    def categories(self, *, distro: str | None = None) -> list[str]:
        return self._catalog().categories(distro=distro)

    def get_entry(self, name: str):
        return self._catalog().get_entry(name)

    def preflight_entry(self, entry) -> list[str]:
        runtime = self.services.runtime_for(self.chroot_name)
        missing: list[str] = []
        required = list(getattr(entry, "requires_commands", ()))
        if str(getattr(entry, "script", "")).endswith(".py") and "python3" not in required:
            required.append("python3")
        risks = set(getattr(entry, "risks", ()))
        if "package-mutation" in risks:
            record = self.services.registry.get(runtime.config.distro_name) or {}
            distro = str(record.get("distro") or "").lower()
            package_command = {"ubuntu": "apt-get", "arch": "pacman"}.get(distro)
            if package_command and package_command not in required:
                required.append(package_command)
        for command in required:
            result = runtime.runner.run(["busybox", "chroot", str(runtime.config.chroot_base), "/bin/bash", "-lc", f"command -v {command} >/dev/null 2>&1"], check=False, chroot_env=True)
            if result.returncode != 0:
                missing.append(command)
        return missing

    def apply(
        self,
        names: list[str],
        *,
        progress: Callable[[Any], None] | None = None,
    ) -> list[CatalogApplyResult]:
        runtime = self.services.runtime_for(self.chroot_name)
        catalog = self._catalog()
        ordered_names = list(dict.fromkeys(names))
        for name in ordered_names:
            catalog.get_entry(name)
        results: list[CatalogApplyResult] = []
        for name in ordered_names:
            if progress is not None:
                progress({"phase": "catalog", "message": f"Applying {self.kind}: {name}", "kind": self.kind, "name": name})
            results.append(
                catalog.apply(
                    name=name,
                    config=runtime.config,
                    runner=runtime.runner,
                    registry=self.services.registry,
                    logger=self.services.logger,
                )
            )
        return results
