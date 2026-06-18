from __future__ import annotations

from collections.abc import Callable

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

    def apply(
        self,
        names: list[str],
        *,
        progress: Callable[[str], None] | None = None,
    ) -> list[CatalogApplyResult]:
        runtime = self.services.runtime_for(self.chroot_name)
        catalog = self._catalog()
        results: list[CatalogApplyResult] = []
        for name in names:
            if progress is not None:
                progress(f"Applying {self.kind}: {name}")
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
