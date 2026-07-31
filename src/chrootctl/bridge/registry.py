from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..operations.manager import OperationCancelled
from ..services import ServiceContainer
from .protocol import BridgeProtocolError, BridgeRequest, serialize_value

QueryHandler = Callable[[ServiceContainer, dict[str, Any]], Any]
PreviewHandler = Callable[[ServiceContainer, dict[str, Any]], Any]
OperationHandler = Callable[[ServiceContainer, dict[str, Any], Callable[[Any], None], Callable[[], bool]], Any]


@dataclass(frozen=True, slots=True)
class OperationSpec:
    name: str
    mode: str
    description: str
    destructive: bool = False
    lock_scope: str = "none"
    query_handler: QueryHandler | None = None
    preview_handler: PreviewHandler | None = None
    operation_handler: OperationHandler | None = None

    def capability(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "description": self.description,
            "destructive": self.destructive,
            "lockScope": self.lock_scope,
        }


def _required_name(payload: dict[str, Any]) -> str:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise BridgeProtocolError("MISSING_CHROOT_NAME", "payload.name is required")
    return name


def _dashboard(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    target = str(payload.get("name") or "").strip() or None
    return services.system().dashboard(target_name=target, details=bool(payload.get("details", True)), tail=int(payload.get("tail", 20)))


def _chroots_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    return services.chroots().list()


def _chroots_get(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.chroots().get(_required_name(payload))


def _status(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.system().status(_required_name(payload), details=bool(payload.get("details", True)))


def _doctor(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.system().doctor(_required_name(payload))


def _delete_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.chroots().delete_preview(_required_name(payload))


def _export_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    archive = payload.get("archive")
    from pathlib import Path

    return services.chroots().export_preview(_required_name(payload), archive=Path(str(archive)) if archive else None)


def _refresh(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    progress({"phase": "runtime", "percent": 10, "message": "Resolving chrootctl runtime"})
    if cancelled():
        raise OperationCancelled("Refresh was cancelled")
    progress({"phase": "registry", "percent": 35, "message": "Reading chroot registry"})
    chroots = services.chroots().list()
    if cancelled():
        raise OperationCancelled("Refresh was cancelled")
    progress({"phase": "dashboard", "percent": 70, "message": "Collecting dashboard state"})
    dashboard = _dashboard(services, payload)
    progress({"phase": "complete", "percent": 100, "message": "State refresh completed"})
    return {"dashboard": serialize_value(dashboard), "chroots": serialize_value(chroots)}


_SPECS = (
    OperationSpec("system.dashboard", "query", "Return native dashboard state", query_handler=_dashboard),
    OperationSpec("system.status", "query", "Return status checks for one chroot", query_handler=_status),
    OperationSpec("system.doctor", "query", "Return doctor checks for one chroot", query_handler=_doctor),
    OperationSpec("chroots.list", "query", "List registered chroots", query_handler=_chroots_list),
    OperationSpec("chroots.get", "query", "Return one registered chroot", query_handler=_chroots_get),
    OperationSpec(
        "chroots.remove",
        "preview",
        "Preview removal without mutating data",
        destructive=True,
        lock_scope="target",
        preview_handler=_delete_preview,
    ),
    OperationSpec("chroots.export", "preview", "Preview a chroot export", preview_handler=_export_preview),
    OperationSpec("system.refresh", "operation", "Persist and stream a complete read-only refresh", operation_handler=_refresh),
)
SPECS = {spec.name: spec for spec in _SPECS}


def resolve_spec(request: BridgeRequest, expected_mode: str) -> OperationSpec:
    spec = SPECS.get(request.operation)
    if spec is None:
        raise BridgeProtocolError("UNSUPPORTED_OPERATION", f"Unsupported operation: {request.operation}")
    if spec.mode != expected_mode:
        raise BridgeProtocolError(
            "OPERATION_MODE_MISMATCH",
            f"Operation {request.operation} is a {spec.mode} operation, not {expected_mode}",
        )
    return spec


def capabilities() -> list[dict[str, Any]]:
    return [spec.capability() for spec in _SPECS]
