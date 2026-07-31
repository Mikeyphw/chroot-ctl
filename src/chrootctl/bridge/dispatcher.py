from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..operations import OperationManager
from ..services import ServiceContainer
from .protocol import BridgeProtocolError, BridgeRequest, BridgeResponse, serialize_value
from .registry import capabilities, resolve_spec


class BridgeDispatcher:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services
        self.operation_manager = OperationManager(operation_root_for(services))

    def capabilities(self) -> dict[str, Any]:
        return {
            "protocolVersion": 1,
            "backendVersion": _backend_version(),
            "operations": capabilities(),
            "operationRoot": str(self.operation_manager.journal.root),
            "transport": ["json", "ndjson"],
            "arbitraryShell": False,
        }

    def state(self, *, request_id: str = "state") -> BridgeResponse:
        try:
            dashboard = self.services.system().dashboard(details=True, tail=20)
            operations = [item.to_dict() for item in self.operation_manager.list_recent(limit=20)]
            return BridgeResponse.success(request_id, {"dashboard": serialize_value(dashboard), "operations": operations})
        except Exception as exc:
            return BridgeResponse.failure(request_id, exc)

    def query(self, request: BridgeRequest) -> BridgeResponse:
        try:
            spec = resolve_spec(request, "query")
            assert spec.query_handler is not None
            result = spec.query_handler(self.services, request.payload)
            return BridgeResponse.success(request.request_id, result)
        except Exception as exc:
            return BridgeResponse.failure(request.request_id, _as_protocol_error(exc))

    def preview(self, request: BridgeRequest) -> BridgeResponse:
        try:
            spec = resolve_spec(request, "preview")
            assert spec.preview_handler is not None
            result = spec.preview_handler(self.services, request.payload)
            return BridgeResponse.success(request.request_id, result)
        except Exception as exc:
            return BridgeResponse.failure(request.request_id, _as_protocol_error(exc))

    def run(self, request: BridgeRequest, emit: Callable[[dict[str, Any]], None]) -> int:
        try:
            spec = resolve_spec(request, "operation")
            assert spec.operation_handler is not None
            target = str(request.payload.get("name") or "").strip() or None
            record = self.operation_manager.create(
                kind=spec.name,
                title=str(request.payload.get("title") or spec.description),
                target_name=target,
                request={
                    "protocolVersion": request.protocol_version,
                    "requestId": request.request_id,
                    "operation": request.operation,
                    "payload": request.payload,
                },
                retry={
                    "protocolVersion": request.protocol_version,
                    "requestId": request.request_id,
                    "operation": request.operation,
                    "payload": request.payload,
                },
                lock_scope=spec.lock_scope,
            )

            def event_sink(event: dict[str, Any]) -> None:
                event["protocolVersion"] = request.protocol_version
                event["requestId"] = request.request_id
                emit(event)

            completed = self.operation_manager.execute(
                record,
                lambda progress, cancelled: spec.operation_handler(self.services, request.payload, progress, cancelled),
                emit=event_sink,
            )
            return 0 if completed.state == "succeeded" else 2
        except Exception as exc:
            error = BridgeResponse.failure(request.request_id, _as_protocol_error(exc)).to_dict()
            error.update({"type": "bridge_error", "operationId": ""})
            emit(error)
            return 2

    def operation(self, operation_id: str) -> BridgeResponse:
        try:
            return BridgeResponse.success(operation_id, self.operation_manager.get(operation_id).to_dict())
        except KeyError:
            return BridgeResponse.failure(operation_id, BridgeProtocolError("UNKNOWN_OPERATION_ID", f"Unknown operation: {operation_id}"))
        except Exception as exc:
            return BridgeResponse.failure(operation_id, exc)

    def cancel(self, operation_id: str) -> BridgeResponse:
        try:
            return BridgeResponse.success(operation_id, self.operation_manager.cancel(operation_id).to_dict())
        except KeyError:
            return BridgeResponse.failure(operation_id, BridgeProtocolError("UNKNOWN_OPERATION_ID", f"Unknown operation: {operation_id}"))
        except Exception as exc:
            return BridgeResponse.failure(operation_id, exc)


def operation_root_for(services: ServiceContainer) -> Path:
    return services.base_config.database_path.parent / "operations"


def _backend_version() -> str:
    try:
        from importlib.metadata import version

        return version("chrootctl")
    except Exception:
        from .. import __version__

        return __version__


def _as_protocol_error(error: Exception) -> Exception:
    if isinstance(error, BridgeProtocolError):
        return error
    if isinstance(error, KeyError):
        return BridgeProtocolError("NOT_FOUND", str(error))
    if isinstance(error, (TypeError, ValueError)):
        return BridgeProtocolError("INVALID_ARGUMENT", str(error))
    return error
