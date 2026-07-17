
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import InstallRequest
from .context import ServiceContainer


class PreviewService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def install(self, request: InstallRequest) -> dict[str, Any]:
        return self.services.install().preview_install(request)

    def export(self, *, name: str, archive: str | None = None) -> dict[str, Any]:
        return self.services.chroots().export_preview(name.strip(), archive=Path(archive).expanduser() if archive else None)

    def import_(self, *, archive: str, name: str | None = None, conflict: str = "rename") -> dict[str, Any]:
        return self.services.chroots().import_preview(Path(archive).expanduser(), name=name, conflict=conflict)

    def delete(self, *, name: str) -> dict[str, Any]:
        return self.services.chroots().delete_preview(name.strip())

    def upgrade(self, *, name: str) -> dict[str, Any]:
        record = self.services.registry.get(name)
        if record is None:
            raise RuntimeError(f"unknown chroot: {name}")
        return {
            "name": name,
            "distro": str(record.get("distro", "")),
            "phase": str(record.get("phase", "")),
            "installed": bool(record.get("installed")),
            "dry_run": {
                "supported": True,
                "command": f"chrootctl --name {name} upgrade --dry-run",
            },
            "warnings": [] if bool(record.get("installed")) else ["Chroot is not marked fully installed yet."],
            "blocking": [] if bool(record.get("path")) else [{"code": "missing_path", "message": "No chroot path is registered."}],
        }
