
from __future__ import annotations

from typing import Any

from ..web.serialize import serialize_value
from .context import ServiceContainer


class DoctorService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def host_readiness(self) -> dict[str, Any]:
        rows = self.services.system().host_doctor()
        advisories = self.services.system().foreign_arch_advisories()
        blockers = [serialize_value(row) for row in rows if getattr(row, "result", "") == "FAIL"]
        blockers.extend(item for item in advisories if item.get("mode") != "ready")
        return {
            "host_arch": self.services.runtime_for().runner.host_arch(),
            "checks": [serialize_value(row) for row in rows],
            "summary": {
                "pass": sum(1 for row in rows if getattr(row, "result", "") == "PASS"),
                "warn": sum(1 for row in rows if getattr(row, "result", "") == "WARN"),
                "fail": sum(1 for row in rows if getattr(row, "result", "") == "FAIL"),
            },
            "advisories": advisories,
            "blockers": blockers,
        }

    def cross_arch_readiness(self) -> dict[str, Any]:
        return self.services.system().cross_arch_state()
