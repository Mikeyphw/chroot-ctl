from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..operations import OperationManager
from ..operations.manager import OperationCancelled
from ..services import ServiceContainer
from .previews import (
    PREVIEW_REQUIRED_OPERATIONS,
    PreviewContractStore,
    action_operation_for_preview,
    preview_payload_for_action,
    preview_resource_revision,
)
from .protocol import BridgeProtocolError, BridgeRequest, BridgeResponse, serialize_value
from .registry import SPECS, capabilities, resolve_spec


class BridgeDispatcher:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services
        # Queries and previews must be read-only. Stale-operation reconciliation is
        # therefore explicit and happens only at operation execution boundaries.
        self.operation_manager = OperationManager(operation_root_for(services))
        self.preview_contracts = PreviewContractStore(self.operation_manager.journal.root.parent / "previews")

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
            action_operation = action_operation_for_preview(request.operation, request.payload)
            if action_operation is not None and action_operation in PREVIEW_REQUIRED_OPERATIONS:
                contract = self.preview_contracts.issue(
                    preview_operation=request.operation,
                    action_operation=action_operation,
                    preview_payload=request.payload,
                    preview_result=result,
                )
                if isinstance(result, dict):
                    result = {**result, **contract}
                else:
                    result = {"ok": True, "result": serialize_value(result), **contract}
            return BridgeResponse.success(request.request_id, result)
        except Exception as exc:
            return BridgeResponse.failure(request.request_id, _as_protocol_error(exc))

    def run(self, request: BridgeRequest, emit: Callable[[dict[str, Any]], None]) -> int:
        try:
            self.operation_manager.recover()
            if request.operation == "operations.retry":
                return self._run_retry(request, emit)
            spec = resolve_spec(request, "operation")
            assert spec.operation_handler is not None
            self._verify_preview_contract(request.operation, request.payload)
            return self._run_spec(request, spec, request.payload, emit)
        except Exception as exc:
            error = BridgeResponse.failure(request.request_id, _as_protocol_error(exc)).to_dict()
            error.update({"type": "bridge_error", "operationId": ""})
            try:
                emit(error)
            except (BrokenPipeError, ConnectionError, OSError):
                pass
            return 2

    def _verify_preview_contract(self, operation: str, payload: dict[str, Any]) -> None:
        if operation not in PREVIEW_REQUIRED_OPERATIONS:
            return
        record = self.preview_contracts.verify_fields(operation, payload)
        preview_target = preview_payload_for_action(
            operation,
            payload,
            preview_operation=str(record.get("previewOperation") or "") or None,
        )
        if preview_target is None:
            raise BridgeProtocolError("PREVIEW_CONTRACT_UNSUPPORTED", f"No preview contract is defined for {operation}")
        preview_operation, preview_payload = preview_target
        preview_spec = SPECS.get(preview_operation)
        if preview_spec is None or preview_spec.preview_handler is None:
            raise BridgeProtocolError("PREVIEW_CONTRACT_UNSUPPORTED", f"Preview operation {preview_operation} is unavailable")
        current_preview = preview_spec.preview_handler(self.services, preview_payload)
        current_revision = preview_resource_revision(current_preview)
        if current_revision != str(record.get("resourceRevision") or ""):
            raise BridgeProtocolError(
                "PREVIEW_STALE",
                "Resource state changed after preview; review the updated preview before applying the action.",
            )

    def _run_spec(
        self,
        request: BridgeRequest,
        spec: Any,
        payload: dict[str, Any],
        emit: Callable[[dict[str, Any]], None],
        *,
        parent_operation_id: str | None = None,
        retry_mode: str | None = None,
    ) -> int:
        target = str(payload.get("name") or "").strip() or None
        retry_payload = dict(payload)
        retry_request = {
            "protocolVersion": request.protocol_version,
            "requestId": request.request_id,
            "operation": spec.name,
            "payload": retry_payload,
        }
        record = self.operation_manager.create(
            kind=spec.name,
            title=str(payload.get("title") or spec.description),
            target_name=target,
            request=retry_request,
            retry=retry_request,
            lock_scope=spec.lock_scope,
            parent_operation_id=parent_operation_id,
        )

        def event_sink(event: dict[str, Any]) -> None:
            event["protocolVersion"] = request.protocol_version
            event["requestId"] = request.request_id
            if parent_operation_id is not None:
                event["parentOperationId"] = parent_operation_id
            if retry_mode is not None:
                event["retryMode"] = retry_mode
            emit(event)

        completed = self.operation_manager.execute(
            record,
            lambda progress, cancelled: spec.operation_handler(self.services, payload, progress, cancelled),
            emit=event_sink,
        )
        return 0 if completed.state == "succeeded" else 2

    def _run_retry(self, request: BridgeRequest, emit: Callable[[dict[str, Any]], None]) -> int:
        resolve_spec(request, "operation")
        operation_id = str(
            request.payload.get("operationId")
            or request.payload.get("operation_id")
            or request.payload.get("id")
            or ""
        ).strip()
        if not operation_id:
            raise BridgeProtocolError("MISSING_OPERATION_ID", "payload.operationId is required")
        mode = str(request.payload.get("mode") or "retry").strip() or "retry"
        if mode not in {"retry", "repair"}:
            raise BridgeProtocolError("INVALID_RETRY_MODE", f"Unsupported retry mode: {mode}")

        parent = self.operation_manager.get(operation_id)
        stored = parent.retry or parent.request
        if not isinstance(stored, dict) or not stored:
            raise BridgeProtocolError("RETRY_REQUEST_UNAVAILABLE", "The operation journal does not contain a retry request")
        if _contains_redacted(stored):
            raise BridgeProtocolError(
                "REDACTED_RETRY_REQUEST",
                "The stored retry request contains redacted secrets; re-enter the sensitive fields instead of replaying it.",
            )
        original_operation = str(stored.get("operation") or "").strip()
        original_payload = dict(stored.get("payload") or {}) if isinstance(stored.get("payload"), dict) else {}
        if not original_operation or original_operation == "operations.retry":
            raise BridgeProtocolError("INVALID_RETRY_OPERATION", "The stored request cannot be replayed")
        spec = SPECS.get(original_operation)
        if spec is None or spec.mode != "operation" or spec.operation_handler is None:
            raise BridgeProtocolError("UNSUPPORTED_RETRY_OPERATION", f"Cannot retry unsupported operation: {original_operation}")
        if original_operation in PREVIEW_REQUIRED_OPERATIONS:
            raise BridgeProtocolError(
                "PREVIEW_RETRY_REQUIRES_PREVIEW",
                "Preview-bound operations must be previewed again before retrying so stale approvals cannot be replayed.",
            )
        if mode == "repair":
            if original_operation != "install.run":
                raise BridgeProtocolError("RETRY_FIXES_UNSUPPORTED", "Retry with fixes is available only for install operations")
            original_payload["repair"] = True
            original_payload["resume"] = True

        child_request = BridgeRequest(
            protocol_version=request.protocol_version,
            request_id=request.request_id,
            operation=original_operation,
            payload=original_payload,
        )
        return self._run_spec(
            child_request,
            spec,
            original_payload,
            emit,
            parent_operation_id=operation_id,
            retry_mode=mode,
        )

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

    def reconcile(self, operation_id: str) -> BridgeResponse:
        try:
            return BridgeResponse.success(operation_id, self.operation_manager.reconcile(operation_id).to_dict())
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


def _contains_redacted(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_redacted(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_redacted(item) for item in value)
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return text in {"<redacted>", "[redacted]", "redacted"} or "<redacted>" in text or "[redacted]" in text
