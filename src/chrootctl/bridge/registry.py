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


def _required_username(payload: dict[str, Any]) -> str:
    username = str(payload.get("username") or "").strip()
    if not username:
        raise BridgeProtocolError("MISSING_USERNAME", "payload.username is required")
    return username


def _required_service(payload: dict[str, Any]) -> str:
    service = str(payload.get("service") or payload.get("serviceName") or payload.get("unit") or "").strip()
    if not service:
        raise BridgeProtocolError("MISSING_SERVICE", "payload.service is required")
    return service


def _payload_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "false", "off", "no"}


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
    tail = int(payload.get("tail", 120))
    runner = _service_runner(services)
    return {
        "status": runner.status(service, chroot=name),
        "journal": runner.logs(service, chroot=name, tail=None if tail == 0 else tail),
    }


def _services_journal(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    service = _required_service(payload)
    name = _optional_text(payload, "name") or _optional_text(payload, "chroot")
    tail = int(payload.get("tail", 120))
    runner = _service_runner(services)
    return {
        "status": runner.status(service, chroot=name),
        "journal": runner.logs(service, chroot=name, tail=None if tail == 0 else tail),
    }


def _service_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    service = _required_service(payload)
    name = _optional_text(payload, "name") or _optional_text(payload, "chroot")
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


_SPECS = (
    OperationSpec("system.dashboard", "query", "Return native dashboard state", query_handler=_dashboard),
    OperationSpec("system.status", "query", "Return status checks for one chroot", query_handler=_status),
    OperationSpec("system.doctor", "query", "Return doctor checks for one chroot", query_handler=_doctor),
    OperationSpec("chroots.list", "query", "List registered chroots", query_handler=_chroots_list),
    OperationSpec("chroots.get", "query", "Return one registered chroot", query_handler=_chroots_get),
    OperationSpec("install.form", "query", "Return native install form state", query_handler=_install_form),
    OperationSpec("snapshots.list", "query", "List snapshots for one or all chroots", query_handler=_snapshot_list),
    OperationSpec("users.list", "query", "List chroot users", query_handler=_users_list),
    OperationSpec("users.get", "query", "Return one chroot user with UID/GID status", query_handler=_users_get),
    OperationSpec("services.list", "query", "List chroot service units", query_handler=_services_list),
    OperationSpec("services.get", "query", "Return service status and journal", query_handler=_services_get),
    OperationSpec("services.journal", "query", "Return service journal with status context", query_handler=_services_journal),
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
    OperationSpec("system.refresh", "operation", "Persist and stream a complete read-only refresh", operation_handler=_refresh),
    OperationSpec("install.run", "operation", "Run the native install flow", lock_scope="global", operation_handler=_install_run),
    OperationSpec("chroots.start", "operation", "Start a chroot session", lock_scope="target", operation_handler=_start_chroot),
    OperationSpec("chroots.restart", "operation", "Restart a chroot session", lock_scope="target", operation_handler=_restart_chroot),
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
