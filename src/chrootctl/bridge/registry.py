from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..models import InstallRequest
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


def _required_snapshot(payload: dict[str, Any]) -> str:
    snapshot = str(payload.get("snapshot") or payload.get("snapshotName") or payload.get("snapshot_name") or "").strip()
    if not snapshot:
        raise BridgeProtocolError("MISSING_SNAPSHOT_NAME", "payload.snapshot is required")
    return snapshot


def _install_request(payload: dict[str, Any]) -> InstallRequest:
    distro = str(payload.get("distro") or "ubuntu").strip() or "ubuntu"
    name = str(payload.get("name") or distro).strip() or distro
    username = str(payload.get("username") or "mike").strip() or "mike"
    tools = tuple(str(item).strip() for item in payload.get("tools", ()) if str(item).strip()) if isinstance(payload.get("tools", ()), (list, tuple)) else ()
    addons = tuple(str(item).strip() for item in payload.get("addons", ()) if str(item).strip()) if isinstance(payload.get("addons", ()), (list, tuple)) else ()
    return InstallRequest(
        distro=distro,
        name=name,
        username=username,
        preset=_optional_text(payload, "preset"),
        profile=_optional_text(payload, "profile"),
        desktop=_optional_text(payload, "desktop"),
        release=_optional_text(payload, "release"),
        version=_optional_text(payload, "version"),
        mirror=_optional_text(payload, "mirror"),
        phase=_optional_text(payload, "phase"),
        force_phase=bool(payload.get("forcePhase") or payload.get("force_phase") or False),
        resume=bool(payload.get("resume") or False),
        repair=bool(payload.get("repair") or False),
        tools=tools,
        addons=addons,
    )


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _install_form(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.install().install_form_state(name=_optional_text(payload, "name"), distro=_optional_text(payload, "distro"))


def _install_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.install().preview_install(_install_request(payload))


def _delete_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.chroots().delete_preview(_required_name(payload))


def _export_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    archive = payload.get("archive")
    return services.chroots().export_preview(_required_name(payload), archive=Path(str(archive)) if archive else None)


def _lifecycle_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    action = str(payload.get("action") or "start").strip() or "start"
    if action not in {"start", "restart", "remove", "upgrade"}:
        raise BridgeProtocolError("INVALID_LIFECYCLE_ACTION", f"Unsupported lifecycle action: {action}")
    if action == "remove":
        return services.chroots().delete_preview(name)
    if action == "upgrade":
        return services.preview().upgrade(name=name)
    detail = services.chroots().get(name)
    return {
        "ok": True,
        "kind": action,
        "name": name,
        "path": detail.path,
        "installed": detail.installed,
        "warnings": [] if detail.installed else ["Chroot is not marked fully installed yet."],
        "blocking": [] if detail.path else [{"code": "missing_path", "message": "No chroot path is registered."}],
        "confirm": action in {"restart"},
        "dry_run": {"supported": True, "command": f"chrootctl --name {name} {action} --dry-run"},
    }


def _snapshot_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.snapshots().list(chroot_name=_optional_text(payload, "name"), limit=int(payload.get("limit", 100)))


def _snapshot_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    action = str(payload.get("action") or "create").strip() or "create"
    snapshot = _optional_text(payload, "snapshot") or _optional_text(payload, "snapshotName")
    archive = _optional_text(payload, "archive")
    existing = services.snapshots().list(chroot_name=name, limit=100)
    if action == "create":
        requested = snapshot or "snapshot"
        conflict = any(str(getattr(item, "name", "")) == requested for item in existing)
        return {
            "ok": not conflict,
            "kind": "snapshot.create",
            "name": name,
            "snapshot": requested,
            "existingCount": len(existing),
            "blocking": [{"code": "snapshot_exists", "message": f"Snapshot already exists: {requested}"}] if conflict else [],
            "warnings": [],
            "confirm": False,
        }
    if action == "restore":
        requested = snapshot or _required_snapshot(payload)
        return {
            "ok": True,
            "kind": "snapshot.restore",
            "name": name,
            "snapshot": requested,
            "destructive": True,
            "blocking": [],
            "warnings": ["Restore replaces the current chroot files with the selected snapshot."],
            "confirm": True,
        }
    if action == "export":
        requested = snapshot or _required_snapshot(payload)
        return {
            "ok": True,
            "kind": "snapshot.export",
            "name": name,
            "snapshot": requested,
            "archive": archive or f"./{name}-{requested}.tar.gz",
            "blocking": [],
            "warnings": [],
            "confirm": False,
        }
    raise BridgeProtocolError("INVALID_SNAPSHOT_ACTION", f"Unsupported snapshot action: {action}")


def _operations_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..operations import OperationManager

    target = str(payload.get("name") or "").strip() or None
    limit = int(payload.get("limit", 50))
    manager = OperationManager(services.base_config.database_path.parent / "operations")
    return [record.to_dict() for record in manager.list_recent(limit=limit, target_name=target)]


def _operations_get(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..operations import OperationManager

    operation_id = str(payload.get("operationId") or payload.get("operation_id") or payload.get("id") or "").strip()
    if not operation_id:
        raise BridgeProtocolError("MISSING_OPERATION_ID", "payload.operationId is required")
    manager = OperationManager(services.base_config.database_path.parent / "operations")
    return manager.get(operation_id).to_dict()


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


def _install_run(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    request = _install_request(payload)
    progress({"phase": "preview", "percent": 3, "message": "Preparing install preview"})
    preview = services.install().preview_install(request)
    if not bool(preview.get("ok", False)):
        raise BridgeProtocolError("INSTALL_PREVIEW_BLOCKED", "Install preview reported blocking issues")
    if cancelled():
        raise OperationCancelled("Install was cancelled before execution")

    def _progress(event: Any) -> None:
        progress(event)
        if cancelled():
            raise OperationCancelled("Install was cancelled")

    return services.install().install(request, progress=_progress)


def _start_chroot(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    name = _required_name(payload)
    progress({"phase": "start", "percent": 10, "message": f"Starting {name}"})
    if cancelled():
        raise OperationCancelled("Start was cancelled")
    result = services.chroots().start(name, login=bool(payload.get("login", True)), root_login=bool(payload.get("rootLogin", payload.get("root_login", False))))
    progress({"phase": "complete", "percent": 100, "message": f"Started {name}"})
    return result


def _restart_chroot(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    name = _required_name(payload)
    progress({"phase": "restart", "percent": 10, "message": f"Restarting {name}"})
    if cancelled():
        raise OperationCancelled("Restart was cancelled")
    result = services.chroots().restart(name, login=bool(payload.get("login", True)), root_login=bool(payload.get("rootLogin", payload.get("root_login", False))))
    progress({"phase": "complete", "percent": 100, "message": f"Restarted {name}"})
    return result


def _remove_chroot(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    name = _required_name(payload)
    expected = str(payload.get("confirmation") or payload.get("confirmName") or "").strip()
    if expected != name:
        raise BridgeProtocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.name")
    progress({"phase": "preview", "percent": 5, "message": f"Previewing removal of {name}"})
    preview = services.chroots().delete_preview(name)
    if cancelled():
        raise OperationCancelled("Removal was cancelled")
    progress({"phase": "remove", "percent": 40, "message": f"Removing {name}", "preview": preview})
    result = services.chroots().remove(name)
    progress({"phase": "complete", "percent": 100, "message": f"Removed {name}"})
    return result


def _snapshot_create(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    name = _required_name(payload)
    snapshot = _optional_text(payload, "snapshot") or _optional_text(payload, "snapshotName") or "snapshot"
    progress({"phase": "snapshot", "percent": 10, "message": f"Creating snapshot {snapshot}"})
    if cancelled():
        raise OperationCancelled("Snapshot creation was cancelled")
    result = services.snapshots().create(name, name=snapshot, note=_optional_text(payload, "note") or "")
    progress({"phase": "complete", "percent": 100, "message": f"Created snapshot {snapshot}"})
    return result


def _snapshot_restore(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    name = _required_name(payload)
    snapshot = _required_snapshot(payload)
    expected = str(payload.get("confirmation") or "").strip()
    if expected != name:
        raise BridgeProtocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.name")
    progress({"phase": "restore", "percent": 10, "message": f"Restoring {snapshot}"})
    if cancelled():
        raise OperationCancelled("Snapshot restore was cancelled")
    result = services.snapshots().restore(name, snapshot)
    progress({"phase": "complete", "percent": 100, "message": f"Restored snapshot {snapshot}"})
    return result


def _snapshot_export(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    name = _required_name(payload)
    snapshot = _required_snapshot(payload)
    archive = _optional_text(payload, "archive")
    progress({"phase": "export", "percent": 10, "message": f"Exporting snapshot {snapshot}"})
    if cancelled():
        raise OperationCancelled("Snapshot export was cancelled")
    result = services.snapshots().export(name, snapshot, archive=Path(archive) if archive else None)
    progress({"phase": "complete", "percent": 100, "message": f"Exported snapshot {snapshot}"})
    return result


_SPECS = (
    OperationSpec("system.dashboard", "query", "Return native dashboard state", query_handler=_dashboard),
    OperationSpec("system.status", "query", "Return status checks for one chroot", query_handler=_status),
    OperationSpec("system.doctor", "query", "Return doctor checks for one chroot", query_handler=_doctor),
    OperationSpec("chroots.list", "query", "List registered chroots", query_handler=_chroots_list),
    OperationSpec("chroots.get", "query", "Return one registered chroot", query_handler=_chroots_get),
    OperationSpec("install.form", "query", "Return native install form state", query_handler=_install_form),
    OperationSpec("snapshots.list", "query", "List snapshots for one or all chroots", query_handler=_snapshot_list),
    OperationSpec("operations.list", "query", "List persistent operation records", query_handler=_operations_list),
    OperationSpec("operations.get", "query", "Return one persistent operation with events", query_handler=_operations_get),
    OperationSpec("install.preview", "preview", "Preview a native install request", preview_handler=_install_preview),
    OperationSpec("chroots.lifecycle.preview", "preview", "Preview chroot lifecycle mutation", preview_handler=_lifecycle_preview),
    OperationSpec(
        "chroots.remove",
        "preview",
        "Preview removal without mutating data",
        destructive=True,
        lock_scope="target",
        preview_handler=_delete_preview,
    ),
    OperationSpec("chroots.export", "preview", "Preview a chroot export", preview_handler=_export_preview),
    OperationSpec("snapshots.preview", "preview", "Preview snapshot create/restore/export", destructive=True, preview_handler=_snapshot_preview),
    OperationSpec("system.refresh", "operation", "Persist and stream a complete read-only refresh", operation_handler=_refresh),
    OperationSpec("install.run", "operation", "Run the native install flow", lock_scope="global", operation_handler=_install_run),
    OperationSpec("chroots.start", "operation", "Start a chroot session", lock_scope="target", operation_handler=_start_chroot),
    OperationSpec("chroots.restart", "operation", "Restart a chroot session", lock_scope="target", operation_handler=_restart_chroot),
    OperationSpec("chroots.remove.execute", "operation", "Remove a chroot after typed confirmation", destructive=True, lock_scope="target", operation_handler=_remove_chroot),
    OperationSpec("snapshots.create", "operation", "Create a chroot snapshot", lock_scope="target", operation_handler=_snapshot_create),
    OperationSpec("snapshots.restore", "operation", "Restore a chroot snapshot", destructive=True, lock_scope="target", operation_handler=_snapshot_restore),
    OperationSpec("snapshots.export", "operation", "Export a chroot snapshot", lock_scope="target", operation_handler=_snapshot_export),
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
