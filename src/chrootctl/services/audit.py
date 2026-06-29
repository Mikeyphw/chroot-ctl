from __future__ import annotations

from ..models import AuditEvent
from .context import ServiceContainer


class AuditService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def record(
        self,
        event_type: str,
        *,
        target: str = "",
        result: str = "ok",
        message: str = "",
        actor: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        username = actor or self.services.base_config.username or "unknown"
        return self.services.registry.add_event(
            event_type=event_type,
            actor=username,
            target=target,
            result=result,
            message=message,
            metadata=metadata or {},
        )

    def recent(self, limit: int = 20) -> list[AuditEvent]:
        return self.services.registry.list_events(limit=limit)
