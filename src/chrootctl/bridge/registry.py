from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any, Callable

from ..models import InstallRequest
from ..operations.manager import OperationCancelled
from ..services import ServiceContainer
from ..validation import (
    optional_bool,
    optional_bounded_int,
    strict_string_list,
    unique_catalog_names,
    validate_catalog_name,
    validate_chroot_name,
    validate_service_name,
    validate_snapshot_name,
    validate_username,
)
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
    try:
        return validate_chroot_name(name, field="payload.name")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_CHROOT_NAME", str(exc)) from exc


def _required_snapshot(payload: dict[str, Any]) -> str:
    snapshot = str(payload.get("snapshot") or payload.get("snapshotName") or payload.get("snapshot_name") or "").strip()
    if not snapshot:
        raise BridgeProtocolError("MISSING_SNAPSHOT_NAME", "payload.snapshot is required")
    try:
        return validate_snapshot_name(snapshot, field="payload.snapshot")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_SNAPSHOT_NAME", str(exc)) from exc


def _install_request(payload: dict[str, Any]) -> InstallRequest:
    distro = str(payload.get("distro") or "ubuntu").strip() or "ubuntu"
    raw_username = str(payload.get("username") or "").strip()
    if not raw_username:
        raise BridgeProtocolError("MISSING_INSTALL_USERNAME", "payload.username is required")
    try:
        name = validate_chroot_name(str(payload.get("name") or distro).strip() or distro, field="payload.name")
        username = validate_username(raw_username, field="payload.username")
        tools = tuple(validate_catalog_name(item, field="payload.tools item") for item in strict_string_list(payload.get("tools", []), field="payload.tools"))
        addons = tuple(validate_catalog_name(item, field="payload.addons item") for item in strict_string_list(payload.get("addons", []), field="payload.addons"))
        force_phase = optional_bool(payload, "forcePhase", "force_phase", default=False, field="payload.forcePhase")
        resume = optional_bool(payload, "resume", default=False, field="payload.resume")
        repair = optional_bool(payload, "repair", default=False, field="payload.repair")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_INSTALL_PAYLOAD", str(exc)) from exc
    return InstallRequest(
        distro=distro,
        name=name,
        username=username,
        arch=(_optional_text(payload, "arch") or "arm64").lower(),
        preset=_optional_text(payload, "preset"),
        profile=_optional_text(payload, "profile"),
        desktop=_optional_text(payload, "desktop"),
        release=_optional_text(payload, "release"),
        version=_optional_text(payload, "version"),
        mirror=_optional_text(payload, "mirror"),
        phase=_optional_text(payload, "phase"),
        force_phase=force_phase,
        resume=resume,
        repair=repair,
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
    target = None
    if _optional_text(payload, "name"):
        target = _required_name(payload)
    try:
        details = optional_bool(payload, "details", default=True, field="payload.details")
        tail = optional_bounded_int(payload, "tail", default=20, minimum=0, maximum=500)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_DASHBOARD_PAYLOAD", str(exc)) from exc
    return services.system().dashboard(target_name=target, details=details, tail=tail)


def _chroots_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    return services.chroots().list()


def _chroots_get(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.chroots().get(_required_name(payload))


def _status(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    try:
        details = optional_bool(payload, "details", default=True, field="payload.details")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_STATUS_PAYLOAD", str(exc)) from exc
    return services.system().status(_required_name(payload), details=details)


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
    name = _optional_text(payload, "name")
    if name is not None:
        name = _required_name(payload)
    try:
        limit = optional_bounded_int(payload, "limit", default=100, minimum=0, maximum=500)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_SNAPSHOT_LIMIT", str(exc)) from exc
    return services.snapshots().list(chroot_name=name, limit=limit)


def _snapshot_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    action = str(payload.get("action") or "create").strip() or "create"
    snapshot = _optional_text(payload, "snapshot") or _optional_text(payload, "snapshotName")
    archive = _optional_text(payload, "archive")
    existing = services.snapshots().list(chroot_name=name, limit=100)
    mounted = [
        row for row in services.runtime_for(name).controller.status(verbose=True)
        if str(row.get("mounted", "")).lower() == "yes"
    ]
    mount_blocking = [{"code": "chroot_mounted", "message": "Snapshot create/restore requires the chroot to be fully unmounted."}] if mounted else []
    if action == "create":
        try:
            requested = validate_snapshot_name(snapshot or "snapshot", field="payload.snapshot")
        except ValueError as exc:
            raise BridgeProtocolError("INVALID_SNAPSHOT_NAME", str(exc)) from exc
        conflict = any(str(getattr(item, "name", "")) == requested for item in existing)
        blocking = ([{"code": "snapshot_exists", "message": f"Snapshot already exists: {requested}"}] if conflict else []) + mount_blocking
        return {
            "ok": not blocking,
            "kind": "snapshot.create",
            "name": name,
            "snapshot": requested,
            "existingCount": len(existing),
            "blocking": blocking,
            "warnings": [],
            "confirm": False,
        }
    if action == "restore":
        requested = _required_snapshot({**payload, "snapshot": snapshot}) if snapshot else _required_snapshot(payload)
        exists = any(str(getattr(item, "name", "")) == requested for item in existing)
        blocking = ([] if exists else [{"code": "snapshot_missing", "message": f"Snapshot does not exist: {requested}"}]) + mount_blocking
        return {
            "ok": not blocking,
            "kind": "snapshot.restore",
            "name": name,
            "snapshot": requested,
            "destructive": True,
            "blocking": blocking,
            "warnings": ["Restore replaces the current chroot files with the selected snapshot."],
            "confirm": True,
        }
    if action == "export":
        requested = _required_snapshot({**payload, "snapshot": snapshot}) if snapshot else _required_snapshot(payload)
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

    target = _optional_text(payload, "name")
    if target is not None:
        target = _required_name(payload)
    try:
        limit = optional_bounded_int(payload, "limit", default=50, minimum=0, maximum=1000)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_OPERATION_LIMIT", str(exc)) from exc
    manager = OperationManager(services.base_config.database_path.parent / "operations")
    return [record.to_dict() for record in manager.list_recent(limit=limit, target_name=target)]


def _operations_get(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..operations import OperationManager

    operation_id = str(payload.get("operationId") or payload.get("operation_id") or payload.get("id") or "").strip()
    if not operation_id:
        raise BridgeProtocolError("MISSING_OPERATION_ID", "payload.operationId is required")
    manager = OperationManager(services.base_config.database_path.parent / "operations")
    return manager.get(operation_id).to_dict()




def _contains_redacted(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_redacted(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_redacted(item) for item in value)
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return text in {"<redacted>", "[redacted]", "redacted"} or "<redacted>" in text or "[redacted]" in text


def _retry_operation(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    from ..operations import OperationManager

    operation_id = str(payload.get("operationId") or payload.get("operation_id") or payload.get("id") or "").strip()
    if not operation_id:
        raise BridgeProtocolError("MISSING_OPERATION_ID", "payload.operationId is required")
    mode = str(payload.get("mode") or "retry").strip() or "retry"
    if mode not in {"retry", "repair"}:
        raise BridgeProtocolError("INVALID_RETRY_MODE", f"Unsupported retry mode: {mode}")
    manager = OperationManager(services.base_config.database_path.parent / "operations")
    record = manager.get(operation_id)
    retry = record.retry or record.request
    if not isinstance(retry, dict) or not retry:
        raise BridgeProtocolError("RETRY_REQUEST_UNAVAILABLE", "The operation journal does not contain a retry request")
    if _contains_redacted(retry):
        raise BridgeProtocolError(
            "REDACTED_RETRY_REQUEST",
            "The stored retry request contains redacted secrets; re-enter the sensitive fields instead of replaying it.",
        )
    original_operation = str(retry.get("operation") or "").strip()
    original_payload = dict(retry.get("payload") or {}) if isinstance(retry.get("payload"), dict) else {}
    if not original_operation or original_operation == "operations.retry":
        raise BridgeProtocolError("INVALID_RETRY_OPERATION", "The stored request cannot be replayed")
    spec = SPECS.get(original_operation)
    if spec is None or spec.operation_handler is None:
        raise BridgeProtocolError("UNSUPPORTED_RETRY_OPERATION", f"Cannot retry unsupported operation: {original_operation}")
    if mode == "repair":
        if original_operation != "install.run":
            raise BridgeProtocolError("RETRY_FIXES_UNSUPPORTED", "Retry with fixes is available only for install operations")
        original_payload["repair"] = True
        original_payload["resume"] = True
    progress({"phase": "retry", "percent": 5, "message": f"Preparing retry for {original_operation}"})
    if cancelled():
        raise OperationCancelled("Retry was cancelled before execution")
    result = spec.operation_handler(services, original_payload, progress, cancelled)
    return {
        "retriedOperationId": operation_id,
        "operation": original_operation,
        "mode": mode,
        "result": serialize_value(result),
        "next_steps": ["Review the new operation record in Activity."],
    }


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
    try:
        login = optional_bool(payload, "login", default=False, field="payload.login")
        root_login = optional_bool(payload, "rootLogin", "root_login", default=False, field="payload.rootLogin")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_BOOLEAN", str(exc)) from exc
    result = services.chroots().start(name, login=login, root_login=root_login, interactive=False)
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
    try:
        login = optional_bool(payload, "login", default=False, field="payload.login")
        root_login = optional_bool(payload, "rootLogin", "root_login", default=False, field="payload.rootLogin")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_BOOLEAN", str(exc)) from exc
    result = services.chroots().restart(name, login=login, root_login=root_login, interactive=False)
    progress({"phase": "complete", "percent": 100, "message": f"Restarted {name}"})
    return result

def _upgrade_chroot(
    services: ServiceContainer,
    payload: dict[str, Any],
    progress: Callable[[Any], None],
    cancelled: Callable[[], bool],
) -> Any:
    name = _required_name(payload)
    username = _optional_text(payload, "username")
    progress({"phase": "preview", "percent": 5, "message": f"Previewing upgrade for {name}"})
    preview = services.preview().upgrade(name=name)
    blocking = preview.get("blocking") or []
    preview_ok = bool(preview.get("ok", len(blocking) == 0))
    if not preview_ok:
        raise BridgeProtocolError("UPGRADE_PREVIEW_BLOCKED", "Upgrade preview reported blocking issues")
    if cancelled():
        raise OperationCancelled("Upgrade was cancelled before execution")

    def _progress(event: Any) -> None:
        progress(event)
        if cancelled():
            raise OperationCancelled("Upgrade was cancelled")

    progress({"phase": "upgrade", "percent": 20, "message": f"Upgrading {name}", "preview": preview})
    result = services.install().upgrade(name, username=username, progress=_progress)
    progress({"phase": "complete", "percent": 100, "message": f"Upgraded {name}"})
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


def _storage_status(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.chroots().storage_status(_required_name(payload))


def _logs_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    if services.registry.get(name) is None:
        raise BridgeProtocolError("UNKNOWN_CHROOT", f"unknown chroot: {name}")
    try:
        tail = optional_bounded_int(payload, "tail", default=200, minimum=0, maximum=500)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_LOG_TAIL", str(exc)) from exc
    tail = max(20, min(tail, 500))
    level = str(payload.get("level") or "").strip().upper() or None
    if level not in {None, "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise BridgeProtocolError("INVALID_LOG_LEVEL", "payload.level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    snapshot = services.system().logs(name, tail=tail, level=level, follow=False)
    return {
        "name": name,
        "logFile": str(snapshot.log_file),
        "level": snapshot.level or "",
        "tail": tail,
        "entries": [
            {"line": entry.line, "level": entry.level or ""}
            for entry in snapshot.entries
        ],
    }


def _required_username(payload: dict[str, Any]) -> str:
    username = str(payload.get("username") or "").strip()
    if not username:
        raise BridgeProtocolError("MISSING_USERNAME", "payload.username is required")
    try:
        return validate_username(username, field="payload.username")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_USERNAME", str(exc)) from exc


def _required_service(payload: dict[str, Any]) -> str:
    service = str(payload.get("service") or payload.get("serviceName") or payload.get("unit") or "").strip()
    if not service:
        raise BridgeProtocolError("MISSING_SERVICE", "payload.service is required")
    try:
        return validate_service_name(service, field="payload.service")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_SERVICE", str(exc)) from exc


def _payload_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    try:
        return optional_bool(payload, key, default=default, field=f"payload.{key}")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_BOOLEAN", str(exc)) from exc


def _users_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return services.users(name=_required_name(payload)).list()


def _users_get(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    user_service = services.users(name=name)
    return {"user": user_service.show(username), "ids": user_service.show_id(username)}


def _user_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    action = str(payload.get("action") or "add").strip() or "add"
    if action not in {"add", "remove", "sync_uid_gid", "set_shell", "set_sudo", "set_password"}:
        raise BridgeProtocolError("INVALID_USER_ACTION", f"Unsupported user action: {action}")
    blocking: list[dict[str, str]] = []
    warnings: list[str] = []
    confirm_username = action in {"remove", "set_password"}
    if action == "add" and not str(payload.get("shell") or "/bin/bash").strip().startswith("/"):
        blocking.append({"code": "invalid_shell", "message": "Shell must be an absolute path."})
    if action == "set_password":
        warnings.append("Password input is accepted only for immediate execution and is redacted from operation journals.")
    if action == "remove":
        warnings.append("Removing a user may also delete the home directory when deleteHome is enabled.")
    return {
        "ok": not blocking,
        "kind": f"users.{action}",
        "name": name,
        "username": username,
        "shell": str(payload.get("shell") or "/bin/bash").strip() or "/bin/bash",
        "sudo": _payload_bool(payload, "sudo", False),
        "deleteHome": _payload_bool(payload, "deleteHome", False),
        "destructive": action in {"remove", "set_password"},
        "confirmUsername": confirm_username,
        "blocking": blocking,
        "warnings": warnings,
        "confirm": confirm_username,
    }


def _user_add(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    shell = str(payload.get("shell") or "/bin/bash").strip() or "/bin/bash"
    sudo = _payload_bool(payload, "sudo", False)
    progress({"phase": "user", "percent": 10, "message": f"Adding user {username}"})
    if cancelled():
        raise OperationCancelled("User add was cancelled")
    result = services.users(name=name).add(username, shell=shell, sudo=sudo)
    progress({"phase": "complete", "percent": 100, "message": f"Added user {username}"})
    return result


def _user_remove(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    expected = str(payload.get("confirmation") or payload.get("confirmUsername") or "").strip()
    if expected != username:
        raise BridgeProtocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.username")
    delete_home = _payload_bool(payload, "deleteHome", False)
    progress({"phase": "user", "percent": 10, "message": f"Removing user {username}"})
    if cancelled():
        raise OperationCancelled("User removal was cancelled")
    result = services.users(name=name).remove(username, delete_home=delete_home)
    progress({"phase": "complete", "percent": 100, "message": f"Removed user {username}"})
    return result


def _user_sync_id(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    fix_ownership = _payload_bool(payload, "fixOwnership", True)
    progress({"phase": "identity", "percent": 10, "message": f"Syncing UID/GID for {username}"})
    if cancelled():
        raise OperationCancelled("User identity sync was cancelled")
    result = services.users(name=name).sync_id(username, fix_ownership=fix_ownership)
    progress({"phase": "complete", "percent": 100, "message": f"Synced UID/GID for {username}"})
    return result


def _user_set_shell(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    shell = str(payload.get("shell") or "").strip()
    if not shell:
        raise BridgeProtocolError("MISSING_SHELL", "payload.shell is required")
    progress({"phase": "shell", "percent": 10, "message": f"Setting shell for {username}"})
    if cancelled():
        raise OperationCancelled("Set shell was cancelled")
    result = services.users(name=name).set_shell(username, shell=shell)
    progress({"phase": "complete", "percent": 100, "message": f"Updated shell for {username}"})
    return result


def _user_set_sudo(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    enabled = _payload_bool(payload, "enabled", _payload_bool(payload, "sudo", True))
    progress({"phase": "sudo", "percent": 10, "message": ("Enabling" if enabled else "Disabling") + f" sudo for {username}"})
    if cancelled():
        raise OperationCancelled("Set sudo was cancelled")
    result = services.users(name=name).set_sudo(username, enabled=enabled)
    progress({"phase": "complete", "percent": 100, "message": "Updated sudo state"})
    return result


def _user_set_password(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    name = _required_name(payload)
    username = _required_username(payload)
    expected = str(payload.get("confirmation") or payload.get("confirmUsername") or "").strip()
    if expected != username:
        raise BridgeProtocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.username")
    password = str(payload.get("password") or "")
    confirm_password = payload.get("confirmPassword")
    if not password:
        raise BridgeProtocolError("MISSING_PASSWORD", "payload.password is required")
    if confirm_password is not None and str(confirm_password) != password:
        raise BridgeProtocolError("PASSWORD_CONFIRMATION_MISMATCH", "payload.confirmPassword does not match payload.password")
    progress({"phase": "password", "percent": 10, "message": f"Updating password for {username}"})
    if cancelled():
        raise OperationCancelled("Set password was cancelled")
    result = services.users(name=name).set_password(username, password=password)
    progress({"phase": "complete", "percent": 100, "message": f"Updated password for {username}"})
    return result


def _service_runner(services: ServiceContainer):
    from ..runtime.units import ServiceRunner

    return ServiceRunner.from_services(services)


def _services_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _optional_text(payload, "name")
    rows = _service_runner(services).list()
    if name:
        rows = [row for row in rows if str(row.get("chroot") or "") == name]
    return rows


def _services_get(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    service = _required_service(payload)
    name = _optional_text(payload, "name") or _optional_text(payload, "chroot")
    if name is not None:
        name = validate_chroot_name(name, field="payload.name")
    try:
        tail = optional_bounded_int(payload, "tail", default=120, minimum=0, maximum=500)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_SERVICE_TAIL", str(exc)) from exc
    runner = _service_runner(services)
    return {
        "status": runner.status(service, chroot=name),
        "journal": runner.logs(service, chroot=name, tail=None if tail == 0 else tail),
    }


def _services_journal(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    service = _required_service(payload)
    name = _optional_text(payload, "name") or _optional_text(payload, "chroot")
    if name is not None:
        name = validate_chroot_name(name, field="payload.name")
    try:
        tail = optional_bounded_int(payload, "tail", default=120, minimum=0, maximum=500)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_SERVICE_TAIL", str(exc)) from exc
    runner = _service_runner(services)
    return {
        "status": runner.status(service, chroot=name),
        "journal": runner.logs(service, chroot=name, tail=None if tail == 0 else tail),
    }


def _service_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    service = _required_service(payload)
    name = _optional_text(payload, "name") or _optional_text(payload, "chroot")
    if name is not None:
        name = validate_chroot_name(name, field="payload.name")
    action = str(payload.get("action") or "start").strip() or "start"
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        raise BridgeProtocolError("INVALID_SERVICE_ACTION", f"Unsupported service action: {action}")
    status = _service_runner(services).status(service, chroot=name)
    warnings = []
    if action in {"stop", "restart"} and status.get("status") not in {"running", "stale"}:
        warnings.append("Service is not currently running.")
    return {
        "ok": True,
        "kind": f"services.{action}",
        "name": status.get("chroot") or name,
        "service": service,
        "status": status,
        "blocking": [],
        "warnings": warnings,
        "confirm": action in {"restart", "disable"},
    }


def _service_action(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    service = _required_service(payload)
    name = _optional_text(payload, "name") or _optional_text(payload, "chroot")
    if name is not None:
        name = validate_chroot_name(name, field="payload.name")
    action = str(payload.get("action") or "start").strip() or "start"
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        raise BridgeProtocolError("INVALID_SERVICE_ACTION", f"Unsupported service action: {action}")
    runner = _service_runner(services)
    progress({"phase": "service", "percent": 10, "message": f"{action.replace('_', ' ').title()} {service}"})
    if cancelled():
        raise OperationCancelled("Service action was cancelled")
    if action == "start":
        result = runner.start(service, chroot=name)
    elif action == "stop":
        result = runner.stop(service, chroot=name)
    elif action == "restart":
        result = runner.restart(service, chroot=name)
    elif action == "enable":
        result = runner.enable(service, chroot=name, target=str(payload.get("target") or "boot.target"))
    else:
        result = runner.disable(service, chroot=name, target=str(payload.get("target") or "boot.target"))
    progress({"phase": "complete", "percent": 100, "message": f"Service {action} complete"})
    return result



def _required_catalog_kind(payload: dict[str, Any]) -> str:
    kind = str(payload.get("kind") or "tool").strip().lower() or "tool"
    if kind in {"tools", "tool"}:
        return "tool"
    if kind in {"addons", "addon"}:
        return "addon"
    raise BridgeProtocolError("INVALID_CATALOG_KIND", f"Unsupported catalog kind: {kind}")


def _payload_names(payload: dict[str, Any]) -> list[str]:
    raw: Any = []
    for key in ("names", "entries", "entry"):
        if key in payload:
            raw = payload.get(key)
            break
    if raw in (None, ""):
        return []
    try:
        return list(unique_catalog_names(raw))
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_CATALOG_NAMES", str(exc)) from exc


def _catalog_entry_payload(entry: Any) -> dict[str, Any]:
    script_text = str(getattr(entry, "script_text", ""))
    return {
        "kind": getattr(entry, "kind", "tool"),
        "name": getattr(entry, "name", ""),
        "description": getattr(entry, "description", ""),
        "distros": list(getattr(entry, "distros", ())),
        "categories": list(getattr(entry, "categories", ())),
        "script": getattr(entry, "script", ""),
        "version": getattr(entry, "version", "1"),
        "risks": list(getattr(entry, "risks", ())),
        "rollback": getattr(entry, "rollback", "manual"),
        "requires": list(getattr(entry, "requires_commands", ())),
        "scriptSha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
    }


def _catalog_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    kind = _required_catalog_kind(payload)
    target = _optional_text(payload, "name") or _optional_text(payload, "targetName")
    if target is not None:
        target = validate_chroot_name(target, field="payload.name")
    distro = _optional_text(payload, "distro")
    category = _optional_text(payload, "category")
    query = (_optional_text(payload, "query") or _optional_text(payload, "q") or "").lower()
    catalog = services.catalog(kind, name=target)
    entries = catalog.list_entries(distro=distro, category=category)
    if query:
        entries = [
            entry for entry in entries
            if query in entry.name.lower()
            or query in entry.description.lower()
            or any(query in category_name.lower() for category_name in entry.categories)
            or any(query in distro_name.lower() for distro_name in entry.distros)
        ]
    return {
        "kind": kind,
        "targetName": target,
        "entries": [_catalog_entry_payload(entry) for entry in entries],
        "categories": catalog.categories(distro=distro),
        "distros": services.install().distros(),
        "query": query,
        "category": category,
        "distro": distro,
    }


def _catalog_tools(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return _catalog_list(services, {**payload, "kind": "tool"})


def _catalog_addons(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return _catalog_list(services, {**payload, "kind": "addon"})


def _catalog_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    kind = _required_catalog_kind(payload)
    target = _required_name(payload)
    names = _payload_names(payload)
    if not names:
        return {
            "ok": False,
            "kind": "catalog.apply",
            "name": target,
            "catalogKind": kind,
            "blocking": [{"code": "missing_entries", "message": "Choose at least one catalog entry."}],
            "warnings": [],
            "entries": [],
        }
    detail = services.chroots().get(target)
    target_distro = detail.distro
    catalog = services.catalog(kind, name=target)
    blocking: list[dict[str, str]] = []
    warnings: list[str] = []
    entries: list[dict[str, Any]] = []
    for entry_name in names:
        try:
            entry = catalog.get_entry(entry_name)
        except KeyError:
            blocking.append({"code": "unknown_entry", "message": f"Unknown {kind}: {entry_name}"})
            continue
        entries.append(_catalog_entry_payload(entry))
        if target_distro and not entry.matches_distro(target_distro):
            blocking.append({"code": "unsupported_distro", "message": f"{entry.name} does not support {target_distro}."})
        missing_commands = catalog.preflight_entry(entry)
        if missing_commands:
            blocking.append({"code": "missing_commands", "message": f"{entry.name} requires: {', '.join(missing_commands)}"})
        risks = list(getattr(entry, "risks", ()))
        if risks:
            warnings.append(f"{entry.name} risk: {', '.join(risks)}")
    if not bool(detail.installed):
        blocking.append({"code": "chroot_not_installed", "message": f"{target} is not marked installed."})
    if kind == "addon":
        warnings.append("Add-ons can install desktop packages and may take a long time.")
    return {
        "ok": not blocking,
        "kind": "catalog.apply",
        "name": target,
        "catalogKind": kind,
        "entries": entries,
        "blocking": blocking,
        "warnings": warnings,
        "confirm": bool(blocking) is False and (len(names) > 1 or bool(warnings)),
    }


def _catalog_apply(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    kind = _required_catalog_kind(payload)
    target = _required_name(payload)
    names = _payload_names(payload)
    if not names:
        raise BridgeProtocolError("MISSING_CATALOG_ENTRIES", "payload.names must include at least one catalog entry")
    preview = _catalog_preview(services, {**payload, "kind": kind, "name": target, "names": names})
    if not bool(preview.get("ok", False)):
        raise BridgeProtocolError("CATALOG_PREVIEW_BLOCKED", "Catalog preview reported blocking issues")
    progress({"phase": "catalog", "percent": 5, "message": f"Applying {len(names)} {kind} entries"})
    if cancelled():
        raise OperationCancelled("Catalog apply was cancelled")

    def _progress(event: Any) -> None:
        if isinstance(event, dict):
            payload_event = dict(event)
            payload_event.setdefault("phase", "catalog")
            payload_event.setdefault("percent", 50)
            progress(payload_event)
        else:
            progress({"phase": "catalog", "percent": 50, "message": str(event)})
        if cancelled():
            raise OperationCancelled("Catalog apply was cancelled")

    result = services.catalog(kind, name=target).apply(names, progress=_progress)
    progress({"phase": "complete", "percent": 100, "message": "Catalog apply complete"})
    return result


def _packages_inventory(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..services.chroot_archives import _package_inventory
    from ..services.storage_safety import require_contained

    name = _required_name(payload)
    record = services.registry.get(name)
    if record is None:
        raise BridgeProtocolError("UNKNOWN_CHROOT", f"unknown chroot: {name}")
    config = services.config_for(name)
    rootfs = require_contained(config.chroot_root, Path(str(record.get("path") or config.chroot_base)), label="registered chroot path")
    packages = sorted(_package_inventory(rootfs))
    try:
        limit = optional_bounded_int(payload, "limit", default=500, minimum=0, maximum=5000)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_PACKAGE_LIMIT", str(exc)) from exc
    return {
        "name": name,
        "count": len(packages),
        "packages": packages[:limit],
        "truncated": len(packages) > limit,
    }


def _packages_compare(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    left = str(payload.get("left") or payload.get("leftName") or "").strip()
    right = str(payload.get("right") or payload.get("rightName") or "").strip()
    if not left or not right:
        raise BridgeProtocolError("MISSING_PACKAGE_COMPARE_TARGETS", "payload.left and payload.right are required")
    try:
        left = validate_chroot_name(left, field="payload.left")
        right = validate_chroot_name(right, field="payload.right")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_PACKAGE_COMPARE_TARGETS", str(exc)) from exc
    return services.chroots().package_diff(left, right)


def _managed_transfer_archive(name: str, suffix: str = "tar.zst", *, create_root: bool = True) -> Path:
    from ..services.transfer import managed_transfer_archive

    return managed_transfer_archive(name, suffix, create_root=create_root)


def _managed_artifact_output(payload: dict[str, Any], *, key: str, default: Path, suffix: str, create_root: bool = True) -> Path:
    from ..services.storage_safety import require_contained
    from ..services.transfer import managed_transfer_root

    raw = _optional_text(payload, key)
    raw_candidate = Path(raw).expanduser() if raw else default.expanduser()
    if raw and raw_candidate.is_symlink():
        raise BridgeProtocolError("INVALID_ARTIFACT_PATH", f"payload.{key} must not be a symlink")
    candidate = raw_candidate.resolve()
    root = managed_transfer_root(create=create_root).resolve()
    candidate = require_contained(root, candidate, label=f"payload.{key} managed artifact")
    if candidate == root or not candidate.name.endswith(suffix):
        raise BridgeProtocolError("INVALID_ARTIFACT_PATH", f"payload.{key} must be a managed {suffix} artifact")
    if candidate.exists() and (candidate.is_symlink() or not candidate.is_file()):
        raise BridgeProtocolError("INVALID_ARTIFACT_PATH", f"payload.{key} is not a regular managed artifact")
    return candidate


def _managed_output_preflight(target: Path) -> tuple[bool, str]:
    from ..services.transfer import managed_transfer_root

    root = managed_transfer_root(create=False)
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            return False, "Managed artifact root exists but is not a safe directory."
        try:
            mode_writable = bool(root.stat().st_mode & 0o222)
        except OSError:
            return False, "Managed artifact root metadata is unreadable."
        if not mode_writable or not __import__("os").access(root, __import__("os").W_OK):
            return False, "Managed artifact root is not writable by the current runtime."
    else:
        parent = root.parent
        if parent.is_symlink() or not parent.is_dir():
            return False, "Managed artifact root parent is unavailable or unsafe."
        try:
            mode_writable = bool(parent.stat().st_mode & 0o222)
        except OSError:
            return False, "Managed artifact root parent metadata is unreadable."
        if not mode_writable or not __import__("os").access(parent, __import__("os").W_OK):
            return False, "Managed artifact root cannot be created by the current runtime."
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False, "Managed artifact target escapes the managed root."
    return True, "Managed artifact target is ready."


def _transfer_artifact_root(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    return services.transfer().artifact_root()


def _transfer_inspect_import(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    archive = _optional_text(payload, "archive") or _optional_text(payload, "path")
    if not archive:
        raise BridgeProtocolError("MISSING_ARCHIVE", "payload.archive is required")
    return services.transfer().inspect(archive, password=_optional_text(payload, "password"))


def _transfer_import_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    archive = _optional_text(payload, "archive") or _optional_text(payload, "path")
    if not archive:
        raise BridgeProtocolError("MISSING_ARCHIVE", "payload.archive is required")
    return services.transfer().preview_import(
        archive=archive,
        name=_optional_text(payload, "name"),
        conflict=_optional_text(payload, "conflict") or "rename",
        password=_optional_text(payload, "password"),
    )


def _transfer_preview_export(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    archive = _optional_text(payload, "archive")
    return services.transfer().preview_export(name=name, archive=archive or str(_managed_transfer_archive(name)))


def _artifacts_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    return services.transfer().temp_state()


def _artifacts_cleanup_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    try:
        delete_all = optional_bool(payload, "deleteAll", "delete_all", default=False, field="payload.deleteAll")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_BOOLEAN", str(exc)) from exc
    requested_path = _optional_text(payload, "path")
    artifact_id = _optional_text(payload, "artifactId") or _optional_text(payload, "artifact_id")
    state = services.transfer().temp_state()
    items = [item for item in state.get("items", []) if isinstance(item, dict)]
    selected = items if delete_all else [
        item for item in items
        if (artifact_id and str(item.get("artifactId") or item.get("artifact_id") or "") == artifact_id)
        or (not artifact_id and requested_path and str(item.get("path") or "") == requested_path)
    ]
    return {
        "ok": bool(selected),
        "kind": "artifacts.cleanup",
        "deleteAll": delete_all,
        "artifactId": artifact_id,
        "path": requested_path,
        "selectedCount": len(selected),
        "selectedBytes": sum(int(item.get("size_bytes", item.get("sizeBytes", 0)) or 0) for item in selected),
        "managedRoot": state.get("managedRoot"),
        "blocking": [] if selected else [{"code": "no_matching_artifacts", "message": "No managed artifacts match this cleanup request."}],
        "warnings": ["Cleanup permanently removes the selected managed transfer artifacts."],
        "confirm": bool(selected),
    }


def _transfer_import(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    archive = _optional_text(payload, "archive") or _optional_text(payload, "path")
    if not archive:
        raise BridgeProtocolError("MISSING_ARCHIVE", "payload.archive is required")
    progress({"phase": "preview", "percent": 5, "message": "Inspecting import archive"})
    preview = services.transfer().preview_import(
        archive=archive,
        name=_optional_text(payload, "name"),
        conflict=_optional_text(payload, "conflict") or "rename",
        password=_optional_text(payload, "password"),
    )
    if not bool(preview.get("ok", False)):
        raise BridgeProtocolError("TRANSFER_IMPORT_BLOCKED", "Transfer import preview reported blocking issues")
    if cancelled():
        raise OperationCancelled("Import was cancelled")
    progress({"phase": "import", "percent": 40, "message": f"Importing {Path(archive).name}"})
    result = services.transfer().import_archive(
        archive=Path(archive),
        name=_optional_text(payload, "name"),
        conflict=_optional_text(payload, "conflict") or "rename",
        password=_optional_text(payload, "password"),
        post_import=_optional_text(payload, "postImport") or _optional_text(payload, "post_import") or "register",
    )
    progress({"phase": "complete", "percent": 100, "message": "Import complete"})
    return result


def _transfer_export(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    name = _required_name(payload)
    archive = _optional_text(payload, "archive")
    target_archive = Path(archive) if archive else _managed_transfer_archive(name)
    progress({"phase": "preview", "percent": 5, "message": f"Previewing export for {name}"})
    preview = services.transfer().preview_export(name=name, archive=str(target_archive))
    if not bool(preview.get("ok", False)):
        raise BridgeProtocolError("TRANSFER_EXPORT_BLOCKED", "Transfer export preview reported blocking issues")
    if cancelled():
        raise OperationCancelled("Export was cancelled")
    progress({"phase": "export", "percent": 40, "message": f"Exporting {name}"})
    result = services.transfer().export(name=name, archive=target_archive, password=_optional_text(payload, "password"))
    progress({"phase": "complete", "percent": 100, "message": f"Exported {name}"})
    return result


def _artifacts_cleanup(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    progress({"phase": "cleanup", "percent": 10, "message": "Cleaning transfer artifacts"})
    if cancelled():
        raise OperationCancelled("Artifact cleanup was cancelled")
    try:
        delete_all = optional_bool(payload, "deleteAll", "delete_all", default=False, field="payload.deleteAll")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_BOOLEAN", str(exc)) from exc
    result = services.transfer().delete_temp(
        artifact_id=_optional_text(payload, "artifactId") or _optional_text(payload, "artifact_id"),
        path=_optional_text(payload, "path"),
        delete_all=delete_all,
    )
    progress({"phase": "complete", "percent": 100, "message": "Transfer artifact cleanup complete"})
    return result



def _path_state(path: Path) -> dict[str, Any]:
    exists = path.exists()
    is_symlink = path.is_symlink()
    is_dir = path.is_dir() if exists and not is_symlink else False
    mode_writable = False
    if exists and is_dir and not is_symlink:
        try:
            mode_writable = bool(path.stat().st_mode & 0o222)
        except OSError:
            mode_writable = False
    return {
        "path": str(path),
        "exists": exists,
        "isDir": is_dir,
        "isSymlink": is_symlink,
        "writable": mode_writable,
        "effectiveRootWritable": exists and is_dir and not is_symlink and __import__("os").access(path, __import__("os").W_OK),
    }


def _system_runtime(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    config = services.base_config
    host_rows = services.system().host_doctor()
    return {
        "runtime": {
            "configPath": str(config.default_config_path()),
            "databasePath": str(config.database_path),
            "logFile": str(config.log_file),
            "chrootRoot": str(config.chroot_root),
            "termuxHome": str(config.termux_home),
            "termuxPrefix": str(config.termux_prefix),
            "username": config.username,
            "targetArch": config.target_arch,
        },
        "paths": {
            "chrootRoot": _path_state(config.chroot_root),
            "databaseDir": _path_state(config.database_path.parent),
            "logDir": _path_state(config.log_file.parent),
            "operationsDir": _path_state(config.database_path.parent / "operations"),
            "transferDir": _path_state(_managed_transfer_archive("probe", create_root=False).parent),
        },
        "hostDoctor": serialize_value(host_rows),
        "crossArch": serialize_value(services.system().cross_arch_state()),
        "foreignArchAdvisories": serialize_value(services.system().foreign_arch_advisories()),
    }


def _module_candidates() -> list[Path]:
    """Return diagnostic module locations; only /data/adb/modules is executable."""
    return [
        Path("/data/adb/modules/chrootctl-magisk"),
        Path("/data/adb/modules_update/chrootctl-magisk"),
        Path("/data/adb/ksu/modules_update/chrootctl-magisk"),
    ]


def _module_status(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    return services.module_runtime().status()


def _module_build_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..magisk import MagiskModuleConfig, _compatibility_manifest_payload, resolve_startup_targets
    import json

    try:
        selected = tuple(validate_chroot_name(item, field="payload.startupTargets item") for item in strict_string_list(payload.get("startupTargets", []), field="payload.startupTargets"))
        all_installed = optional_bool(payload, "allInstalled", "all_installed", default=False, field="payload.allInstalled")
        targets = resolve_startup_targets(services, selected_names=selected, all_installed=all_installed)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_MODULE_BUILD_PAYLOAD", str(exc)) from exc
    archive = _managed_artifact_output(payload, key="archive", default=_managed_transfer_archive("chrootctl-magisk", "zip", create_root=False), suffix=".zip", create_root=False)
    config = MagiskModuleConfig()
    blocking: list[dict[str, str]] = []
    artifact_ready, artifact_detail = _managed_output_preflight(archive)
    if not artifact_ready:
        blocking.append({"code": "managed_artifact_unavailable", "message": artifact_detail})
    warnings: list[str] = []
    source_root = config.package_root() / "chrootctl"
    if not source_root.is_dir() or source_root.is_symlink():
        blocking.append({"code": "python_source_missing", "message": f"Missing or unsafe Python package source: {source_root}"})
    compatibility = config.package_root().parent / "docs/release/compatibility-manifest.json"
    module = services.module_runtime().status()
    source_manifest = None
    if compatibility.is_file() and not compatibility.is_symlink():
        try:
            source_manifest = json.loads(compatibility.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            source_manifest = None
    if source_manifest is None:
        installed_state = module.get("installedState") if isinstance(module.get("installedState"), dict) else {}
        compatibility_state = installed_state.get("compatibility") if isinstance(installed_state.get("compatibility"), dict) else {}
        candidate = compatibility_state.get("manifest")
        if isinstance(candidate, dict):
            source_manifest = candidate
    if source_manifest is None:
        blocking.append({"code": "compatibility_manifest_invalid", "message": "No trusted source or active-module compatibility manifest is available."})
    elif source_manifest != _compatibility_manifest_payload(config):
        blocking.append({"code": "compatibility_manifest_drift", "message": "Compatibility manifest does not match module/Python/Android build identity."})
    if module.get("pendingUpdate"):
        warnings.append("A pending module update exists; it is diagnostic only and will not be executed before reboot activation.")
    if not targets:
        warnings.append("No installed startup target was selected; the module will not auto-start chroots.")
    return {
        "ok": not blocking,
        "kind": "system.module_build",
        "archive": str(archive),
        "startupTargets": list(targets),
        "blocking": blocking,
        "warnings": warnings,
        "moduleRuntime": serialize_value(module),
        "confirm": not blocking,
    }


def _support_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del services
    archive = _managed_artifact_output(payload, key="archive", default=_managed_transfer_archive("chrootctl-support-bundle", "tar.gz", create_root=False), suffix=".tar.gz", create_root=False)
    artifact_ready, artifact_detail = _managed_output_preflight(archive)
    blocking = [] if artifact_ready else [{"code": "managed_artifact_unavailable", "message": artifact_detail}]
    return {
        "ok": not blocking,
        "kind": "support.bundle",
        "archive": str(archive),
        "blocking": blocking,
        "warnings": ["The bundle is recursively redacted and byte-bounded, but review it before sharing."],
        "included": ["manifest.json", "events.json", "doctor-host.json", "chroots.json", "config-sanitized.json", "logs/chrootctl.log"],
        "managed": True,
        "confirm": not blocking,
    }


def _strict_repair_decisions(raw_decisions: Any, *, required: bool) -> list[dict[str, str]]:
    if raw_decisions is None and not required:
        return []
    if not isinstance(raw_decisions, list):
        raise BridgeProtocolError("REPAIR_DECISIONS_REQUIRED", "Registry repair decisions must be an explicit list")
    decisions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_decisions):
        if not isinstance(raw, dict):
            raise BridgeProtocolError("INVALID_REPAIR_DECISION", f"Repair decision {index} must be an object")
        item_id = str(raw.get("item_id") or raw.get("itemId") or "").strip()
        action = str(raw.get("action") or "").strip()
        if not item_id or not action:
            raise BridgeProtocolError("INVALID_REPAIR_DECISION", f"Repair decision {index} requires item_id and action")
        if item_id in seen:
            raise BridgeProtocolError("DUPLICATE_REPAIR_DECISION", f"Duplicate repair decision: {item_id}")
        seen.add(item_id)
        decisions.append({"item_id": item_id, "action": action})
    return decisions


def _repair_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    raw_decisions = payload.get("decisions")
    if raw_decisions is not None:
        decisions = _strict_repair_decisions(raw_decisions, required=False)
        plan = services.repair().preview_plan(decisions)
    else:
        items = services.repair().preview_items()
        decisions = [{"item_id": str(item.get("item_id", "")), "action": str(item.get("action", "skip"))} for item in items]
        plan = services.repair().preview_plan(decisions)
        plan["items"] = items
    plan["kind"] = "repair.registry"
    plan["confirm"] = bool(plan.get("ok"))
    return plan


def _cleanup_temp_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    listing = services.transfer().temp_state()
    items = listing.get("items", []) if isinstance(listing, dict) else []
    total = sum(int(item.get("size_bytes", item.get("sizeBytes", 0)) or 0) for item in items if isinstance(item, dict))
    return {
        "ok": bool(items),
        "kind": "cleanup.temp",
        "itemCount": len(items),
        "bytes": total,
        "blocking": [] if items else [{"code": "no_temp_artifacts", "message": "No temporary transfer artifacts were found."}],
        "warnings": ["Cleanup removes managed transfer staging files."],
        "confirm": bool(items),
    }


def _debug_probe_rows(services: ServiceContainer, group: str = "all") -> list[dict[str, Any]]:
    config = services.base_config
    rows: list[dict[str, Any]] = []

    def add(group_name: str, code: str, status: str, detail: str, next_step: str = "") -> None:
        if group in {"all", group_name}:
            rows.append({"group": group_name, "code": code, "status": status, "detail": detail, "next": next_step})

    import sys
    python_path = Path(sys.executable).expanduser()
    python_ok = python_path.is_file() and os.access(python_path, os.X_OK)
    try:
        python_detail = str(python_path.resolve(strict=True)) if python_ok else str(python_path)
    except OSError:
        python_ok = False
        python_detail = str(python_path)
    add("root", "python_runtime", "pass" if python_ok else "fail", f"Bridge Python executable: {python_detail}", "Repair the bridge Python runtime." if not python_ok else "")
    add("backend", "database_path", "pass" if config.database_path.parent.exists() else "warn", str(config.database_path), "Create or repair the database directory." if not config.database_path.parent.exists() else "")
    add("storage", "chroot_root", "pass" if config.chroot_root.exists() else "warn", str(config.chroot_root), "Create the chroot root or run repair." if not config.chroot_root.exists() else "")
    transfer_probe_dir = _managed_transfer_archive("probe", create_root=False).parent
    add("storage", "transfer_dir", "pass" if transfer_probe_dir.exists() else "warn", str(transfer_probe_dir), "Create the transfer staging directory." if not transfer_probe_dir.exists() else "")
    try:
        host_rows = services.system().host_doctor()
        for row in host_rows[:8]:
            status = "pass" if getattr(row, "result", "") == "PASS" else ("fail" if getattr(row, "result", "") == "FAIL" else "warn")
            add("runtime", str(getattr(row, "check", "host")), status, str(getattr(row, "detail", "")), str(getattr(row, "next", "")))
    except Exception as exc:
        add("runtime", "host_doctor", "fail", str(exc), "Run support bundle export and review runtime logs.")
    try:
        repairs = services.repair().preview_items()
        add("recovery", "registry_repair", "pass" if not repairs else "warn", f"{len(repairs)} registry repair item(s) found.", "Open repair preview." if repairs else "")
    except Exception as exc:
        add("recovery", "registry_repair", "fail", str(exc), "Run repair from a terminal or export diagnostics.")
    try:
        operations_root = config.database_path.parent / "operations"
        stale = list(operations_root.glob("*.json")) if operations_root.exists() else []
        add("operations", "operation_journal", "pass", f"{len(stale)} operation record file(s) visible at {operations_root}.")
    except Exception as exc:
        add("operations", "operation_journal", "warn", str(exc), "Repair operation journal permissions.")
    try:
        module = services.module_runtime().status()
        installed_state = module.get("installedState") if isinstance(module.get("installedState"), dict) else {}
        module_path = str(installed_state.get("path") or "/data/adb/modules/chrootctl-magisk")
        status = "pass" if module.get("ready") else ("warn" if module.get("installed") else "warn")
        add("runtime", "module_runtime", status, f"active={bool(module.get('active'))} ready={bool(module.get('ready'))} path={module_path}", "Reboot pending updates or run the module dependency bootstrap." if not module.get("ready") else "")
    except Exception as exc:
        add("runtime", "module_runtime", "warn", str(exc), "Inspect module status and dependency readiness.")
    return rows


def _debug_probes(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    group = str(payload.get("group") or "all").strip() or "all"
    if group not in {"all", "root", "backend", "storage", "runtime", "recovery", "operations"}:
        raise BridgeProtocolError("INVALID_DEBUG_GROUP", "payload.group must be one of all, root, backend, storage, runtime, recovery, operations")
    rows = _debug_probe_rows(services, group)
    return {
        "group": group,
        "probes": rows,
        "passCount": sum(1 for row in rows if row.get("status") == "pass"),
        "warnCount": sum(1 for row in rows if row.get("status") == "warn"),
        "failCount": sum(1 for row in rows if row.get("status") == "fail"),
        "guidedFixes": [row for row in rows if row.get("next")],
    }


def _debug_timeline(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    try:
        limit = optional_bounded_int(payload, "limit", default=50, minimum=0, maximum=500)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_DEBUG_LIMIT", str(exc)) from exc
    events = [event.to_display_dict() for event in services.audit().recent(limit=limit)]
    return {"events": events, "limit": limit}


def _support_bundle(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    archive = _managed_artifact_output(payload, key="archive", default=_managed_transfer_archive("chrootctl-support-bundle", "tar.gz"), suffix=".tar.gz")
    progress({"phase": "support", "percent": 10, "message": "Collecting redacted bounded support evidence"})
    if cancelled():
        raise OperationCancelled("Support bundle export was cancelled")
    result = services.support().export_bundle(archive=archive, jobs=None)
    artifact = services.registry.artifact_by_path(str(result.archive.resolve()))
    if artifact is None:
        raise RuntimeError("support bundle was not registered as a managed artifact")
    progress({"phase": "complete", "percent": 100, "message": "Support bundle exported"})
    return result


def _module_build(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    from ..magisk import MagiskModuleConfig, render_magisk_module, resolve_startup_targets, validate_magisk_module, validate_magisk_zip, zip_magisk_module
    import tempfile

    try:
        selected = tuple(validate_chroot_name(item, field="payload.startupTargets item") for item in strict_string_list(payload.get("startupTargets", []), field="payload.startupTargets"))
        all_installed = optional_bool(payload, "allInstalled", "all_installed", default=False, field="payload.allInstalled")
        targets = resolve_startup_targets(services, selected_names=selected, all_installed=all_installed)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_MODULE_BUILD_PAYLOAD", str(exc)) from exc
    archive = _managed_artifact_output(payload, key="archive", default=_managed_transfer_archive("chrootctl-magisk", "zip"), suffix=".zip")
    progress({"phase": "render", "percent": 20, "message": "Rendering module payload"})
    if cancelled():
        raise OperationCancelled("Module build was cancelled")
    with tempfile.TemporaryDirectory(prefix="chrootctl-module-") as tmp:
        module_dir = Path(tmp) / "module"
        result = render_magisk_module(module_dir, services=services, startup_targets=targets, module_config=MagiskModuleConfig())
        progress({"phase": "validate", "percent": 60, "message": "Deep-validating module layout"})
        validate_magisk_module(result.output_dir)
        if cancelled():
            raise OperationCancelled("Module build was cancelled")
        progress({"phase": "zip", "percent": 82, "message": "Creating and reopening module zip"})
        zip_path = zip_magisk_module(result.output_dir, archive)
        validate_magisk_zip(zip_path)
    artifact = services.transfer().register_artifact(zip_path, kind="module-archive", metadata={"startupTargets": list(targets), "deepValidated": True})
    if artifact is None:
        raise RuntimeError("module archive was not registered as a managed artifact")
    progress({"phase": "complete", "percent": 100, "message": "Validated module zip created"})
    return {"archive": str(zip_path), "startupTargets": list(targets), "bytes": zip_path.stat().st_size, "deepValidated": True}


def _repair_apply(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    decisions = _strict_repair_decisions(payload.get("decisions"), required=True)
    if not decisions:
        raise BridgeProtocolError("REPAIR_DECISIONS_EMPTY", "Select at least one registry repair decision before applying")
    progress({"phase": "repair", "percent": 15, "message": "Applying selected registry repair decisions"})
    if cancelled():
        raise OperationCancelled("Registry repair was cancelled")
    result = services.repair().apply_registry_repair_plan(decisions)
    progress({"phase": "complete", "percent": 100, "message": "Registry repair completed"})
    return result


def _cleanup_temp(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    progress({"phase": "cleanup", "percent": 10, "message": "Cleaning temporary artifacts"})
    if cancelled():
        raise OperationCancelled("Temporary cleanup was cancelled")
    try:
        delete_all = optional_bool(payload, "deleteAll", "delete_all", default=True, field="payload.deleteAll")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_BOOLEAN", str(exc)) from exc
    result = services.transfer().delete_temp(
        artifact_id=_optional_text(payload, "artifactId") or _optional_text(payload, "artifact_id"),
        path=_optional_text(payload, "path"),
        delete_all=delete_all,
    )
    progress({"phase": "complete", "percent": 100, "message": "Temporary cleanup complete"})
    return result


def _debug_export(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    archive = _managed_artifact_output(payload, key="archive", default=_managed_transfer_archive("chrootctl-debug-evidence", "tar.gz"), suffix=".tar.gz")
    try:
        timeline_limit = optional_bounded_int(payload, "limit", default=100, minimum=0, maximum=500)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_DEBUG_LIMIT", str(exc)) from exc
    progress({"phase": "probes", "percent": 10, "message": "Running typed debug probes"})
    probes = _debug_probes(services, payload)
    timeline = _debug_timeline(services, {"limit": timeline_limit})
    if cancelled():
        raise OperationCancelled("Debug export was cancelled")
    bundle = services.support().export_bundle(
        archive=archive,
        jobs=None,
        extra_json={"debug/probes.json": probes, "debug/timeline.json": timeline},
    )
    artifact = services.transfer().register_artifact(bundle.archive, kind="debug-evidence", metadata={"probeGroup": str(payload.get("group") or "all"), "sanitized": True, "containsProbes": True})
    if artifact is None:
        raise RuntimeError("debug evidence was not registered as a managed artifact")
    progress({"phase": "complete", "percent": 100, "message": "Debug evidence exported"})
    return {"archive": str(bundle.archive), "probes": probes, "included": list(bundle.included)}


def _smoke_target_name(services: ServiceContainer, payload: dict[str, Any]) -> str | None:
    requested = _optional_text(payload, "name") or _optional_text(payload, "target")
    if requested:
        try:
            requested = validate_chroot_name(requested, field="payload.name")
        except ValueError as exc:
            raise BridgeProtocolError("INVALID_CHROOT_NAME", str(exc)) from exc
    rows = serialize_value(services.chroots().list())
    installed: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not bool(row.get("installed")):
                continue
            name = str(row.get("name") or "").strip()
            if name:
                installed.append(name)
    if requested:
        if requested not in installed:
            raise BridgeProtocolError("SMOKE_TARGET_UNAVAILABLE", f"payload.name must identify an installed chroot: {requested}")
        return requested
    return installed[0] if installed else None


def _smoke_steps(target_name: str | None = None) -> list[dict[str, Any]]:
    target_payload = {"name": target_name} if target_name else {}
    workspace_required = bool(target_name)
    return [
        {"id": "root_module_discovery", "title": "Root module discovery", "kind": "query", "operation": "system.module_status", "required": True},
        {"id": "bridge_capabilities", "title": "Bridge capabilities", "kind": "query", "operation": "system.dashboard", "required": True},
        {"id": "chroots_list", "title": "Chroots list", "kind": "query", "operation": "chroots.list", "required": True},
        {"id": "operations_list", "title": "Operation history", "kind": "query", "operation": "operations.list", "required": True},
        {"id": "workspace_services", "title": "Services workspace query", "kind": "query", "operation": "services.list", "required": workspace_required, "target": target_name, "payload": target_payload},
        {"id": "workspace_users", "title": "Users workspace query", "kind": "query", "operation": "users.list", "required": workspace_required, "target": target_name, "payload": target_payload},
        {"id": "workspace_snapshots", "title": "Snapshots workspace query", "kind": "query", "operation": "snapshots.list", "required": workspace_required, "target": target_name, "payload": target_payload},
        {"id": "workspace_storage", "title": "Storage workspace query", "kind": "query", "operation": "storage.status", "required": workspace_required, "target": target_name, "payload": target_payload},
        {"id": "workspace_logs", "title": "Logs workspace query", "kind": "query", "operation": "logs.list", "required": workspace_required, "target": target_name, "payload": {**target_payload, "tail": 40}},
        {"id": "workspace_advanced", "title": "Advanced diagnostics query", "kind": "query", "operation": "system.runtime", "required": True},
        {"id": "debug_probes", "title": "Debug probes", "kind": "query", "operation": "debug.probes", "required": True},
        {"id": "support_preview", "title": "Support bundle preview", "kind": "preview", "operation": "support.preview", "required": False},
        {"id": "module_preview", "title": "Module build preview", "kind": "preview", "operation": "system.module_build_preview", "required": False},
        {"id": "transfer_artifacts", "title": "Managed artifacts list", "kind": "query", "operation": "artifacts.list", "required": False},
        {"id": "degraded_protocol_fallback", "title": "Degraded protocol fallback", "kind": "manual", "operation": "android.workspace.degraded_protocol", "required": False},
        {"id": "root_service_reconnect", "title": "RootService reconnect/recovery", "kind": "manual", "operation": "android.root_service.reconnect", "required": False},
    ]

def _smoke_plan(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    scope = str(payload.get("scope") or "real-device").strip() or "real-device"
    if scope != "real-device":
        raise BridgeProtocolError("INVALID_SMOKE_SCOPE", "payload.scope must be real-device")
    try:
        include_optional = optional_bool(payload, "includeOptional", "include_optional", default=True, field="payload.includeOptional")
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_BOOLEAN", str(exc)) from exc
    target_name = _smoke_target_name(services, payload)
    steps = [step for step in _smoke_steps(target_name) if include_optional or step["required"]]
    blocking = [] if target_name else [{"code": "no_installed_smoke_target", "message": "Real-device smoke requires at least one installed chroot target."}]
    return {
        "ok": not blocking,
        "kind": "smoke.plan",
        "scope": scope,
        "stepCount": len(steps),
        "target": target_name,
        "steps": steps,
        "blocking": blocking,
        "warnings": ["Smoke probes are read-only except for the operation journal entry created by smoke.run."],
        "confirm": not blocking,
    }


def _smoke_report(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..operations import OperationManager

    try:
        limit = optional_bounded_int(payload, "limit", default=12, minimum=1, maximum=100)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_SMOKE_LIMIT", str(exc)) from exc
    manager = OperationManager(services.base_config.database_path.parent / "operations")
    recent = [record.to_dict() for record in manager.list_recent(limit=limit)]
    smoke_records = [item for item in recent if str(item.get("kind") or "") == "smoke.run"]
    latest = smoke_records[0] if smoke_records else None
    failed = _smoke_result_failed(latest)
    manual_pending_count = _smoke_result_manual_pending(latest)
    blocking = []
    if latest is None:
        blocking.append({"code": "no_smoke_run", "message": "No smoke.run operation has been recorded yet."})
    elif failed:
        blocking.append({"code": "smoke_failed", "message": "The latest smoke run contains failed required checks."})
    warnings = [f"{manual_pending_count} manual Android smoke check(s) remain pending."] if manual_pending_count > 0 else []
    return {
        "ok": latest is not None and not failed,
        "kind": "smoke.report",
        "latest": latest,
        "failed": failed,
        "manualPendingCount": manual_pending_count,
        "recentCount": len(smoke_records),
        "blocking": blocking,
        "warnings": warnings,
        "steps": _smoke_steps(_smoke_target_name(services, payload)),
    }


def _run_smoke_step(services: ServiceContainer, step: dict[str, Any]) -> dict[str, Any]:
    step_id = str(step["id"])
    try:
        target = str(step.get("target") or "").strip()
        if step.get("kind") == "manual":
            return {**step, "status": "manual", "message": "Complete this Android real-device check and record the result in smoke evidence."}
        if step_id.startswith("workspace_") and not target and step_id != "workspace_advanced":
            return {**step, "status": "skip", "message": "No registered chroot is available for this workspace query."}
        if step_id == "root_module_discovery":
            module = _module_status(services, {})
            if not isinstance(module.get("active"), dict):
                return {**step, "status": "fail", "message": "No enabled active chrootctl root module was detected."}
            if not bool(module.get("ready")):
                return {**step, "status": "fail", "message": "The active chrootctl root module is not dependency-ready."}
        elif step_id == "bridge_capabilities":
            services.system().dashboard(details=True, tail=5)
        elif step_id == "chroots_list":
            services.chroots().list()
        elif step_id == "operations_list":
            _operations_list(services, {"limit": 5})
        elif step_id == "workspace_services":
            _services_list(services, {"name": target})
        elif step_id == "workspace_users":
            _users_list(services, {"name": target})
        elif step_id == "workspace_snapshots":
            _snapshot_list(services, {"name": target, "limit": 20})
        elif step_id == "workspace_storage":
            _storage_status(services, {"name": target})
        elif step_id == "workspace_logs":
            _logs_list(services, {"name": target, "tail": 40})
        elif step_id == "workspace_advanced":
            _system_runtime(services, {})
        elif step_id == "debug_probes":
            probes = _debug_probes(services, {"group": "all"})
            if int(probes.get("failCount") or 0) > 0:
                return {**step, "status": "warn", "message": f"{probes.get('failCount')} probe(s) failed; review Debug Workbench."}
        elif step_id == "support_preview":
            _support_preview(services, {})
        elif step_id == "module_preview":
            _module_build_preview(services, {})
        elif step_id == "transfer_artifacts":
            _artifacts_list(services, {})
        else:
            return {**step, "status": "warn", "message": "Unknown smoke step skipped."}
        return {**step, "status": "pass", "message": "Completed"}
    except Exception as exc:
        return {**step, "status": "fail" if step.get("required") else "warn", "message": str(exc) or exc.__class__.__name__}


def _smoke_run(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    plan = _smoke_plan(services, payload)
    if not plan.get("ok"):
        raise BridgeProtocolError("SMOKE_PREREQUISITE_FAILED", "Real-device smoke requires an installed chroot target")
    steps = plan["steps"]
    results: list[dict[str, Any]] = []
    total = max(1, len(steps))
    for index, step in enumerate(steps, start=1):
        if cancelled():
            raise OperationCancelled("Smoke suite was cancelled")
        percent = int((index - 1) * 100 / total)
        progress({"phase": str(step["id"]), "percent": percent, "message": str(step["title"])})
        results.append(_run_smoke_step(services, step))
    failed_required = [item for item in results if item.get("required") and item.get("status") == "fail"]
    warnings = [item for item in results if item.get("status") == "warn"]
    manual_pending = [item for item in results if item.get("status") == "manual"]
    progress({"phase": "complete", "percent": 100, "message": "Smoke suite completed"})
    return {
        "ok": not failed_required,
        "kind": "smoke.run",
        "results": results,
        "passCount": sum(1 for item in results if item.get("status") == "pass"),
        "warnCount": len(warnings),
        "failCount": sum(1 for item in results if item.get("status") == "fail"),
        "manualPendingCount": len(manual_pending),
        "manualPending": [str(item.get("id")) for item in manual_pending],
        "blocking": [{"code": str(item.get("id")), "message": str(item.get("message"))} for item in failed_required],
        "warnings": [str(item.get("message")) for item in warnings] + (["Manual Android smoke checks remain pending."] if manual_pending else []),
    }



def _latest_smoke_record(services: ServiceContainer, limit: int = 25) -> dict[str, Any] | None:
    from ..operations import OperationManager

    manager = OperationManager(services.base_config.database_path.parent / "operations")
    recent = [record.to_dict() for record in manager.list_recent(limit=limit)]
    for record in recent:
        if str(record.get("kind") or "") == "smoke.run":
            return record
    return None


def _smoke_result_failed(latest: dict[str, Any] | None) -> bool:
    if latest is None:
        return False
    state = str(latest.get("state") or "").lower()
    result = latest.get("resultPayload") or latest.get("result_payload") or {}
    if not isinstance(result, dict):
        result = {}
    fail_count = result.get("failCount", result.get("fail_count", 0))
    try:
        failed_checks = int(fail_count or 0) > 0
    except (TypeError, ValueError):
        failed_checks = False
    blocking = result.get("blocking")
    return (
        state in {"failed", "interrupted", "blocked"}
        or result.get("ok") is False
        or failed_checks
        or bool(blocking)
    )


def _smoke_result_manual_pending(latest: dict[str, Any] | None) -> int:
    if latest is None:
        return 0
    result = latest.get("resultPayload") or latest.get("result_payload") or {}
    if not isinstance(result, dict):
        return 0
    value = result.get("manualPendingCount", result.get("manual_pending_count", 0))
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _smoke_result_payload(services: ServiceContainer, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = optional_bounded_int(payload, "limit", default=25, minimum=1, maximum=100)
    except ValueError as exc:
        raise BridgeProtocolError("INVALID_SMOKE_LIMIT", str(exc)) from exc
    latest = _latest_smoke_record(services, limit=limit)
    failed = _smoke_result_failed(latest)
    manual_pending_count = _smoke_result_manual_pending(latest)
    blocking = []
    if latest is None:
        blocking.append({"code": "no_smoke_run", "message": "No smoke.run operation has been recorded yet."})
    elif failed:
        blocking.append({"code": "smoke_failed", "message": "The latest smoke run contains failed required checks."})
    warnings = []
    if failed:
        warnings.append("Create a smoke failure support bundle before changing the device state.")
    if manual_pending_count > 0:
        warnings.append(f"{manual_pending_count} manual Android smoke check(s) remain pending.")
    return {
        "ok": latest is not None and not failed,
        "kind": "smoke.last_result",
        "latest": latest,
        "failed": failed,
        "manualPendingCount": manual_pending_count,
        "exportRecommended": latest is not None,
        "supportBundleRecommended": failed,
        "blocking": blocking,
        "warnings": warnings,
    }


def _smoke_last_result(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return _smoke_result_payload(services, payload)


def _write_smoke_result_artifact(services: ServiceContainer, payload: dict[str, Any], suffix: str, *, allow_payload_archive: bool = True) -> Path:
    import json
    import os
    import tempfile

    artifact_payload = payload if allow_payload_archive else {}
    target = _managed_artifact_output(artifact_payload, key="archive", default=_managed_transfer_archive(f"chrootctl-smoke-{suffix}", "json"), suffix=".json")
    data = _smoke_result_payload(services, payload)
    if data.get("latest") is None:
        raise BridgeProtocolError("NO_SMOKE_RESULT", "No smoke.run operation has been recorded yet")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(serialize_value(data), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass
    registered = services.transfer().register_artifact(target, kind="debug-evidence", metadata={"smoke": suffix})
    if registered is None:
        raise RuntimeError("smoke result was not registered as a managed artifact")
    return target


def _smoke_result_persist(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    progress({"phase": "collect", "percent": 15, "message": "Collecting latest smoke result"})
    if cancelled():
        raise OperationCancelled("Smoke result persistence was cancelled")
    artifact = _write_smoke_result_artifact(services, payload, "result")
    progress({"phase": "complete", "percent": 100, "message": "Smoke result artifact persisted"})
    return {"ok": True, "kind": "smoke.result.persist", "artifact": str(artifact), "latest": _smoke_result_payload(services, payload).get("latest")}


def _smoke_result_export(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    progress({"phase": "collect", "percent": 15, "message": "Collecting latest smoke result for export"})
    if cancelled():
        raise OperationCancelled("Smoke evidence export was cancelled")
    artifact = _write_smoke_result_artifact(services, payload, "evidence")
    progress({"phase": "complete", "percent": 100, "message": "Smoke evidence export ready"})
    return {"ok": True, "kind": "smoke.result.export", "artifact": str(artifact), "latest": _smoke_result_payload(services, payload).get("latest")}


def _smoke_failure_bundle(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    latest = _smoke_result_payload(services, payload)
    if latest.get("latest") is None:
        raise BridgeProtocolError("NO_SMOKE_RESULT", "No smoke.run operation has been recorded yet")
    progress({"phase": "smoke-evidence", "percent": 10, "message": "Persisting managed smoke evidence"})
    evidence = _write_smoke_result_artifact(services, payload, "failure-evidence", allow_payload_archive=False)
    if cancelled():
        raise OperationCancelled("Smoke failure bundle was cancelled")
    bundle_payload = {"archive": _optional_text(payload, "archive") or str(_managed_transfer_archive("chrootctl-smoke-failure-bundle", "tar.gz"))}
    bundle = _support_bundle(services, bundle_payload, progress, cancelled)
    progress({"phase": "complete", "percent": 100, "message": "Smoke failure support bundle ready"})
    return {"ok": True, "kind": "smoke.failure.bundle", "evidence": str(evidence), "supportBundle": serialize_value(bundle), "latest": latest.get("latest")}


def _release_readiness(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    evidence = services.release_readiness().status()
    module = services.module_runtime().status()
    checks = list(evidence.get("checks", []))
    module_status = "pass" if bool(module.get("ready")) else ("warn" if bool(module.get("installed")) else "pending")
    optional_checks = [{
        "id": "active_module_runtime",
        "label": "Active module runtime",
        "status": module_status,
        "required": False,
        "detail": "Active module is dependency-ready." if module_status == "pass" else "No dependency-ready active module is currently proven; pending updates are never runtime evidence.",
    }]
    failed = sum(item.get("status") == "fail" for item in checks)
    pending = sum(item.get("status") in {"pending", "warn"} for item in checks)
    passed = sum(item.get("status") == "pass" for item in checks)
    return {
        "ok": bool(evidence.get("ready")),
        "kind": "release.readiness",
        "phase": 26,
        "summary": "Release readiness is derived from recorded validators/builds; missing evidence remains pending.",
        "checks": checks,
        "optionalChecks": optional_checks,
        "passCount": passed,
        "warnCount": pending,
        "failCount": failed,
        "validationEvidence": serialize_value(evidence),
        "module": serialize_value(module),
    }


def _final_audit_tokens() -> dict[str, list[str]]:
    return {
        "bridge": ["system.dashboard", "chroots.list", "operations.list", "smoke.run", "smoke.last_result", "release.readiness", "support.bundle", "debug.export", "transfer.export", "artifacts.cleanup"],
        "webuiRetired": ["FastAPI", "Jinja2", "Uvicorn", "python-multipart", "chrootctl-web"],
        "androidGuardrails": ["SDK 36", "fixed AIDL", "SAF transfer", "foreground operations", "no WebView"],
    }


def _final_no_webui_regression(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    evidence = services.release_readiness().status()
    source = services.release_readiness().check(evidence, "source_no_webui")
    module_zip = services.release_readiness().check(evidence, "module_zip")
    checks = [
        {"id": "web_entry_removed", "status": source.get("status", "pending"), "detail": source.get("detail") or "Awaiting retired-WebUI source scan evidence."},
        {"id": "module_webui_denied", "status": module_zip.get("status", "pending"), "detail": module_zip.get("detail") or "Awaiting deep module ZIP validation evidence."},
    ]
    return {"ok": all(item["status"] == "pass" for item in checks), "kind": "final.no_webui_regression", "checks": checks}


def _final_packaging_audit(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    evidence = services.release_readiness().status()
    module_render = services.release_readiness().check(evidence, "module_render")
    module_zip = services.release_readiness().check(evidence, "module_zip")
    artifact_state = _artifacts_list(services, {})
    managed_root_text = str(artifact_state.get("managedRoot") or artifact_state.get("directory") or "").strip() if isinstance(artifact_state, dict) else ""
    managed_root = Path(managed_root_text) if managed_root_text else None
    artifact_items = [item for item in artifact_state.get("items", []) if isinstance(item, dict)] if isinstance(artifact_state, dict) else []
    managed_ok = managed_root is not None and managed_root.is_dir() and not managed_root.is_symlink()
    if managed_ok:
        resolved_root = managed_root.resolve()
        for item in artifact_items:
            try:
                artifact_path = Path(str(item.get("path") or ""))
                if not bool(item.get("managed")) or artifact_path.is_symlink():
                    managed_ok = False
                    break
                artifact_path.resolve(strict=False).relative_to(resolved_root)
            except (OSError, ValueError):
                managed_ok = False
                break
    checks = [
        {"id": "module_tree", "status": module_render.get("status", "pending"), "detail": module_render.get("detail") or "Awaiting module tree validator evidence."},
        {"id": "module_zip", "status": module_zip.get("status", "pending"), "detail": module_zip.get("detail") or "Awaiting final ZIP validator evidence."},
        {"id": "managed_artifacts", "status": "pass" if managed_ok else "fail", "detail": "Managed artifact registry paths are contained by the managed root." if managed_ok else "Managed artifact root or registry containment is invalid."},
    ]
    return {"ok": all(item["status"] == "pass" for item in checks), "kind": "final.packaging_audit", "module": serialize_value(_module_status(services, {})), "artifacts": serialize_value(artifact_state), "checks": checks}


def _final_preflight(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    runtime = _system_runtime(services, payload)
    release = _release_readiness(services, payload)
    webui = _final_no_webui_regression(services, payload)
    smoke = _smoke_result_payload(services, payload)
    host_rows = runtime.get("hostDoctor") if isinstance(runtime, dict) else []
    host_results = [str(item.get("result") or "").upper() for item in host_rows if isinstance(item, dict)] if isinstance(host_rows, list) else []
    runtime_failures = sum(result == "FAIL" for result in host_results)
    runtime_warnings = sum(result == "WARN" for result in host_results)
    runtime_status = "fail" if runtime_failures else ("pending" if runtime_warnings or not host_results else "pass")
    runtime_detail = (
        f"Host doctor reports {runtime_failures} failure(s) and {runtime_warnings} warning(s)."
        if host_results
        else "Host doctor returned no readiness rows."
    )
    checks = [
        {"id": "runtime", "status": runtime_status, "detail": runtime_detail},
        {"id": "release_readiness", "status": "pass" if bool(release.get("ok")) else ("fail" if int(release.get("failCount") or 0) else "pending"), "detail": str(release.get("summary"))},
        {"id": "webui_regression", "status": "pass" if bool(webui.get("ok")) else ("fail" if any(item.get("status") == "fail" for item in webui.get("checks", [])) else "pending"), "detail": "Retired-WebUI regression requires recorded evidence."},
        {
            "id": "smoke_result",
            "status": "fail" if smoke.get("failed") else ("pending" if smoke.get("latest") is None or int(smoke.get("manualPendingCount") or 0) > 0 else "pass"),
            "detail": (
                "Latest smoke run failed required checks." if smoke.get("failed")
                else f"Latest smoke run has {int(smoke.get('manualPendingCount') or 0)} manual check(s) pending." if int(smoke.get("manualPendingCount") or 0) > 0
                else "Latest smoke result is available." if smoke.get("latest") is not None
                else "Run smoke.run before final release."
            ),
        },
    ]
    return {"ok": all(item["status"] == "pass" for item in checks), "kind": "final.preflight", "runtime": serialize_value(runtime), "release": serialize_value(release), "checks": checks}


def _final_release_seal(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    preflight = _final_preflight(services, payload)
    packaging = _final_packaging_audit(services, payload)
    webui = _final_no_webui_regression(services, payload)
    checks = list(preflight.get("checks", [])) + list(packaging.get("checks", [])) + list(webui.get("checks", []))
    return {"ok": bool(checks) and all(item.get("status") == "pass" for item in checks), "kind": "final.release_seal", "phase": 28, "summary": "Final release seal is evidence-driven; pending checks are not passes.", "checks": checks, "requiredTokens": _final_audit_tokens(), "preflight": serialize_value(preflight), "packaging": serialize_value(packaging), "webuiRegression": serialize_value(webui)}

_SPECS = (
    OperationSpec("system.dashboard", "query", "Return native dashboard state", query_handler=_dashboard),
    OperationSpec("system.status", "query", "Return status checks for one chroot", query_handler=_status),
    OperationSpec("system.doctor", "query", "Return doctor checks for one chroot", query_handler=_doctor),
    OperationSpec("chroots.list", "query", "List registered chroots", query_handler=_chroots_list),
    OperationSpec("chroots.get", "query", "Return one registered chroot", query_handler=_chroots_get),
    OperationSpec("storage.status", "query", "Return structured storage status for one chroot", query_handler=_storage_status),
    OperationSpec("install.form", "query", "Return native install form state", query_handler=_install_form),
    OperationSpec("snapshots.list", "query", "List snapshots for one or all chroots", query_handler=_snapshot_list),
    OperationSpec("users.list", "query", "List chroot users", query_handler=_users_list),
    OperationSpec("users.get", "query", "Return one chroot user with UID/GID status", query_handler=_users_get),
    OperationSpec("services.list", "query", "List chroot service units", query_handler=_services_list),
    OperationSpec("services.get", "query", "Return service status and journal", query_handler=_services_get),
    OperationSpec("services.journal", "query", "Return service journal with status context", query_handler=_services_journal),
    OperationSpec("logs.list", "query", "Return bounded chrootctl log entries for one chroot", query_handler=_logs_list),
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
    OperationSpec("users.preview", "preview", "Preview chroot user mutation", destructive=True, lock_scope="target", preview_handler=_user_preview),
    OperationSpec("services.preview", "preview", "Preview service mutation", lock_scope="target", preview_handler=_service_preview),

    OperationSpec("catalog.tools", "query", "List native tool catalog entries", query_handler=_catalog_tools),
    OperationSpec("catalog.addons", "query", "List native add-on catalog entries", query_handler=_catalog_addons),
    OperationSpec("catalog.search", "query", "Search native catalog entries", query_handler=_catalog_list),
    OperationSpec("packages.inventory", "query", "Return package inventory for one chroot", query_handler=_packages_inventory),
    OperationSpec("packages.compare", "query", "Compare package inventories between chroots", query_handler=_packages_compare),
    OperationSpec("transfer.inspect_import", "query", "Inspect a staged import archive", query_handler=_transfer_inspect_import),
    OperationSpec("artifacts.list", "query", "List managed transfer artifacts", query_handler=_artifacts_list),
    OperationSpec("artifacts.cleanup_preview", "preview", "Preview managed transfer artifact cleanup", destructive=True, preview_handler=_artifacts_cleanup_preview),
    OperationSpec("transfer.artifact_root", "query", "Return the managed transfer artifact root shared by Python and Android", query_handler=_transfer_artifact_root),
    OperationSpec("catalog.preview", "preview", "Preview applying tools or add-ons", preview_handler=_catalog_preview),
    OperationSpec("transfer.import_preview", "preview", "Preview importing a staged archive", preview_handler=_transfer_import_preview),
    OperationSpec("transfer.preview_export", "preview", "Preview exporting a chroot archive", preview_handler=_transfer_preview_export),

    OperationSpec("system.runtime", "query", "Return native system runtime and host readiness", query_handler=_system_runtime),
    OperationSpec("system.module_status", "query", "Return Magisk/KernelSU module status", query_handler=_module_status),
    OperationSpec("support.preview", "preview", "Preview sanitized support bundle export", preview_handler=_support_preview),
    OperationSpec("system.module_build_preview", "preview", "Preview Magisk/KernelSU module build", preview_handler=_module_build_preview),
    OperationSpec("repair.preview", "preview", "Preview registry repair plan", destructive=True, preview_handler=_repair_preview),
    OperationSpec("cleanup.temp_preview", "preview", "Preview managed temporary artifact cleanup", destructive=True, preview_handler=_cleanup_temp_preview),
    OperationSpec("debug.probes", "query", "Run chroot debug workbench probes", query_handler=_debug_probes),
    OperationSpec("debug.timeline", "query", "Return debug audit timeline", query_handler=_debug_timeline),
    OperationSpec("smoke.plan", "query", "Return real-device smoke suite plan", query_handler=_smoke_plan),
    OperationSpec("smoke.preview", "preview", "Preview the real-device smoke suite before execution", preview_handler=_smoke_plan),
    OperationSpec("smoke.report", "query", "Return latest real-device smoke operation report", query_handler=_smoke_report),
    OperationSpec("smoke.last_result", "query", "Return latest smoke result and support handoff guidance", query_handler=_smoke_last_result),
    OperationSpec("release.readiness", "query", "Return native release readiness checklist", query_handler=_release_readiness),
    OperationSpec("final.preflight", "query", "Return final native release preflight summary", query_handler=_final_preflight),
    OperationSpec("final.packaging_audit", "query", "Return final module/package audit summary", query_handler=_final_packaging_audit),
    OperationSpec("final.no_webui_regression", "query", "Return final WebUI retirement regression summary", query_handler=_final_no_webui_regression),
    OperationSpec("final.release_seal", "query", "Return final operational release seal", query_handler=_final_release_seal),
    OperationSpec("operations.retry", "operation", "Retry a recorded operation after redaction checks", destructive=True, lock_scope="global", operation_handler=_retry_operation),
    OperationSpec("system.refresh", "operation", "Persist and stream a complete read-only refresh", operation_handler=_refresh),
    OperationSpec("smoke.run", "operation", "Run real-device read-only operational smoke suite", lock_scope="global", operation_handler=_smoke_run),
    OperationSpec("smoke.result.persist", "operation", "Persist latest smoke result into a managed JSON artifact", lock_scope="global", operation_handler=_smoke_result_persist),
    OperationSpec("smoke.result.export", "operation", "Export latest smoke result evidence into a managed JSON artifact", lock_scope="global", operation_handler=_smoke_result_export),
    OperationSpec("smoke.failure.bundle", "operation", "Create support bundle linked to the latest smoke failure", lock_scope="global", operation_handler=_smoke_failure_bundle),
    OperationSpec("install.run", "operation", "Run the native install flow", lock_scope="global", operation_handler=_install_run),
    OperationSpec("chroots.start", "operation", "Start a chroot session", lock_scope="target", operation_handler=_start_chroot),
    OperationSpec("chroots.restart", "operation", "Restart a chroot session", lock_scope="target", operation_handler=_restart_chroot),
    OperationSpec("chroots.upgrade", "operation", "Upgrade a chroot after preview", destructive=True, lock_scope="target", operation_handler=_upgrade_chroot),
    OperationSpec("chroots.remove.execute", "operation", "Remove a chroot after typed confirmation", destructive=True, lock_scope="target", operation_handler=_remove_chroot),
    OperationSpec("snapshots.create", "operation", "Create a chroot snapshot", lock_scope="target", operation_handler=_snapshot_create),
    OperationSpec("snapshots.restore", "operation", "Restore a chroot snapshot", destructive=True, lock_scope="target", operation_handler=_snapshot_restore),
    OperationSpec("snapshots.export", "operation", "Export a chroot snapshot", lock_scope="target", operation_handler=_snapshot_export),
    OperationSpec("users.add", "operation", "Add a chroot user", lock_scope="target", operation_handler=_user_add),
    OperationSpec("users.remove", "operation", "Remove a chroot user after typed confirmation", destructive=True, lock_scope="target", operation_handler=_user_remove),
    OperationSpec("users.sync_uid_gid", "operation", "Sync UID/GID for a chroot user", lock_scope="target", operation_handler=_user_sync_id),
    OperationSpec("users.set_shell", "operation", "Set a chroot user shell", lock_scope="target", operation_handler=_user_set_shell),
    OperationSpec("users.set_sudo", "operation", "Enable or disable sudo for a chroot user", lock_scope="target", operation_handler=_user_set_sudo),
    OperationSpec("users.set_password", "operation", "Set a chroot user password with redacted request data", destructive=True, lock_scope="target", operation_handler=_user_set_password),
    OperationSpec("services.start", "operation", "Start a chroot service", lock_scope="target", operation_handler=_service_action),
    OperationSpec("services.stop", "operation", "Stop a chroot service", lock_scope="target", operation_handler=_service_action),
    OperationSpec("services.restart", "operation", "Restart a chroot service", lock_scope="target", operation_handler=_service_action),
    OperationSpec("services.enable", "operation", "Enable a chroot service", lock_scope="target", operation_handler=_service_action),
    OperationSpec("services.disable", "operation", "Disable a chroot service", lock_scope="target", operation_handler=_service_action),

    OperationSpec("catalog.apply", "operation", "Apply native tool or add-on catalog entries", lock_scope="target", operation_handler=_catalog_apply),
    OperationSpec("transfer.import", "operation", "Import a staged chroot archive", lock_scope="global", operation_handler=_transfer_import),
    OperationSpec("transfer.export", "operation", "Export a chroot archive to managed artifacts", lock_scope="target", operation_handler=_transfer_export),
    OperationSpec("artifacts.cleanup", "operation", "Clean managed transfer artifacts", destructive=True, lock_scope="global", operation_handler=_artifacts_cleanup),
    OperationSpec("support.bundle", "operation", "Export sanitized support bundle", lock_scope="global", operation_handler=_support_bundle),
    OperationSpec("system.module_build", "operation", "Build Magisk/KernelSU module artifact", lock_scope="global", operation_handler=_module_build),
    OperationSpec("repair.apply", "operation", "Apply selected registry repair plan", destructive=True, lock_scope="global", operation_handler=_repair_apply),
    OperationSpec("cleanup.temp", "operation", "Clean managed temporary artifacts", destructive=True, lock_scope="global", operation_handler=_cleanup_temp),
    OperationSpec("debug.export", "operation", "Export debug workbench evidence bundle", lock_scope="global", operation_handler=_debug_export),
)
SPECS = {spec.name: spec for spec in _SPECS}

_PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "system.dashboard": frozenset({"name", "details", "tail"}),
    "system.status": frozenset({"name", "details"}),
    "system.doctor": frozenset({"name"}),
    "chroots.list": frozenset(),
    "chroots.get": frozenset({"name"}),
    "storage.status": frozenset({"name"}),
    "install.form": frozenset({"name", "distro"}),
    "install.preview": frozenset({"distro", "name", "username", "arch", "preset", "profile", "desktop", "release", "version", "mirror", "phase", "forcePhase", "force_phase", "resume", "repair", "tools", "addons"}),
    "install.run": frozenset({"distro", "name", "username", "arch", "preset", "profile", "desktop", "release", "version", "mirror", "phase", "forcePhase", "force_phase", "resume", "repair", "tools", "addons"}),
    "chroots.lifecycle.preview": frozenset({"name", "action"}),
    "chroots.remove.preview": frozenset({"name"}),
    "chroots.export": frozenset({"name", "archive"}),
    "chroots.start": frozenset({"name", "login", "rootLogin", "root_login"}),
    "chroots.restart": frozenset({"name", "login", "rootLogin", "root_login"}),
    "chroots.upgrade": frozenset({"name", "username"}),
    "chroots.remove.execute": frozenset({"name", "confirmation", "confirmName"}),
    "snapshots.list": frozenset({"name", "limit"}),
    "snapshots.preview": frozenset({"name", "action", "snapshot", "snapshotName", "snapshot_name", "archive"}),
    "snapshots.create": frozenset({"name", "snapshot", "snapshotName", "snapshot_name", "description"}),
    "snapshots.restore": frozenset({"name", "snapshot", "snapshotName", "snapshot_name", "confirmation", "confirmName"}),
    "snapshots.export": frozenset({"name", "snapshot", "snapshotName", "snapshot_name", "archive"}),
    "users.list": frozenset({"name"}),
    "users.get": frozenset({"name", "username"}),
    "users.preview": frozenset({"name", "username", "action", "shell", "sudo", "deleteHome", "fixOwnership", "enabled"}),
    "users.add": frozenset({"name", "username", "shell", "sudo", "action"}),
    "users.remove": frozenset({"name", "username", "confirmation", "confirmUsername", "deleteHome", "action"}),
    "users.sync_uid_gid": frozenset({"name", "username", "fixOwnership", "action"}),
    "users.set_shell": frozenset({"name", "username", "shell", "action"}),
    "users.set_sudo": frozenset({"name", "username", "enabled", "sudo", "action"}),
    "users.set_password": frozenset({"name", "username", "password", "confirmPassword", "confirmation", "confirmUsername", "action"}),
    "services.list": frozenset({"name"}),
    "services.get": frozenset({"name", "chroot", "service", "serviceName", "unit", "tail"}),
    "services.journal": frozenset({"name", "chroot", "service", "serviceName", "unit", "tail"}),
    "services.preview": frozenset({"name", "chroot", "service", "serviceName", "unit", "action", "target"}),
    "services.start": frozenset({"name", "chroot", "service", "serviceName", "unit", "action", "target"}),
    "services.stop": frozenset({"name", "chroot", "service", "serviceName", "unit", "action", "target"}),
    "services.restart": frozenset({"name", "chroot", "service", "serviceName", "unit", "action", "target"}),
    "services.enable": frozenset({"name", "chroot", "service", "serviceName", "unit", "action", "target"}),
    "services.disable": frozenset({"name", "chroot", "service", "serviceName", "unit", "action", "target"}),
    "logs.list": frozenset({"name", "tail", "level"}),
    "operations.list": frozenset({"name", "limit"}),
    "operations.get": frozenset({"operationId", "operation_id", "id"}),
    "operations.retry": frozenset({"operationId", "operation_id", "id", "mode"}),
    "system.refresh": frozenset(),
    "catalog.tools": frozenset({"name", "targetName", "distro", "category", "query", "q"}),
    "catalog.addons": frozenset({"name", "targetName", "distro", "category", "query", "q"}),
    "catalog.search": frozenset({"kind", "name", "targetName", "distro", "category", "query", "q"}),
    "catalog.preview": frozenset({"kind", "name", "names", "entries", "entry"}),
    "catalog.apply": frozenset({"kind", "name", "names", "entries", "entry"}),
    "packages.inventory": frozenset({"name", "limit"}),
    "packages.compare": frozenset({"left", "right", "leftName", "rightName"}),
    "transfer.inspect_import": frozenset({"archive", "path", "password"}),
    "transfer.import_preview": frozenset({"archive", "path", "name", "conflict", "password"}),
    "transfer.preview_export": frozenset({"name", "archive", "password"}),
    "transfer.import": frozenset({"archive", "path", "name", "conflict", "password", "postImport", "post_import"}),
    "transfer.export": frozenset({"name", "archive", "password"}),
    "transfer.artifact_root": frozenset(),
    "artifacts.list": frozenset(),
    "artifacts.cleanup_preview": frozenset({"artifactId", "artifact_id", "path", "deleteAll", "delete_all"}),
    "artifacts.cleanup": frozenset({"artifactId", "artifact_id", "path", "deleteAll", "delete_all"}),
    "system.runtime": frozenset(),
    "system.module_status": frozenset(),
    "support.preview": frozenset({"archive"}),
    "support.bundle": frozenset({"archive"}),
    "system.module_build_preview": frozenset({"startupTargets", "allInstalled", "all_installed", "archive"}),
    "system.module_build": frozenset({"startupTargets", "allInstalled", "all_installed", "archive"}),
    "repair.preview": frozenset({"decisions"}),
    "repair.apply": frozenset({"decisions"}),
    "cleanup.temp_preview": frozenset({"artifactId", "artifact_id", "path", "deleteAll", "delete_all"}),
    "cleanup.temp": frozenset({"artifactId", "artifact_id", "path", "deleteAll", "delete_all"}),
    "debug.probes": frozenset({"group"}),
    "debug.timeline": frozenset({"limit"}),
    "debug.export": frozenset({"archive", "group", "limit"}),
    "smoke.plan": frozenset({"name", "target", "scope", "includeOptional", "include_optional"}),
    "smoke.preview": frozenset({"name", "target", "scope", "includeOptional", "include_optional"}),
    "smoke.report": frozenset({"name", "target", "limit"}),
    "smoke.run": frozenset({"name", "target", "scope", "includeOptional", "include_optional"}),
    "smoke.last_result": frozenset({"limit"}),
    "smoke.result.persist": frozenset({"archive", "limit"}),
    "smoke.result.export": frozenset({"archive", "limit"}),
    "smoke.failure.bundle": frozenset({"archive", "limit"}),
    "release.readiness": frozenset(),
    "final.preflight": frozenset(),
    "final.packaging_audit": frozenset(),
    "final.no_webui_regression": frozenset(),
    "final.release_seal": frozenset(),
}


def resolve_spec(request: BridgeRequest, expected_mode: str) -> OperationSpec:
    spec = SPECS.get(request.operation)
    if spec is None:
        raise BridgeProtocolError("UNSUPPORTED_OPERATION", f"Unsupported operation: {request.operation}")
    if spec.mode != expected_mode:
        raise BridgeProtocolError(
            "OPERATION_MODE_MISMATCH",
            f"Operation {request.operation} is a {spec.mode} operation, not {expected_mode}",
        )
    _validate_payload_fields(request.operation, request.payload)
    return spec


_PREVIEW_CONTRACT_FIELDS = frozenset({"previewId", "payloadHash", "resourceRevision"})


def _validate_payload_fields(operation: str, payload: dict[str, Any]) -> None:
    allowed = _PAYLOAD_FIELDS.get(operation)
    if allowed is None:
        return
    allowed = allowed | _PREVIEW_CONTRACT_FIELDS
    unknown = sorted(key for key in payload.keys() if key not in allowed)
    if unknown:
        raise BridgeProtocolError("UNKNOWN_PAYLOAD_FIELD", f"Unsupported field(s) for {operation}", details={"fields": unknown})


def capabilities() -> list[dict[str, Any]]:
    return [spec.capability() for spec in _SPECS]
