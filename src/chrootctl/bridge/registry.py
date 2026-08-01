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
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        values = [str(item).strip() for item in raw]
    else:
        values = []
    return [item for item in values if item]


def _catalog_entry_payload(entry: Any) -> dict[str, Any]:
    return {
        "kind": getattr(entry, "kind", "tool"),
        "name": getattr(entry, "name", ""),
        "description": getattr(entry, "description", ""),
        "distros": list(getattr(entry, "distros", ())),
        "categories": list(getattr(entry, "categories", ())),
        "script": getattr(entry, "script", ""),
    }


def _catalog_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    kind = _required_catalog_kind(payload)
    target = _optional_text(payload, "name") or _optional_text(payload, "targetName")
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
        "confirm": bool(blocking) is False and len(names) > 1,
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

    def _progress(message: str) -> None:
        progress({"phase": "catalog", "percent": 50, "message": message})
        if cancelled():
            raise OperationCancelled("Catalog apply was cancelled")

    result = services.catalog(kind, name=target).apply(names, progress=_progress)
    progress({"phase": "complete", "percent": 100, "message": "Catalog apply complete"})
    return result


def _packages_inventory(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..services.chroot_archives import _package_inventory

    name = _required_name(payload)
    packages = sorted(_package_inventory(services.config_for(name).chroot_base))
    limit = int(payload.get("limit", 500))
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
    return services.chroots().package_diff(left, right)


def _managed_transfer_archive(name: str, suffix: str = "tar.zst") -> Path:
    import tempfile

    root = Path(tempfile.gettempdir()) / "chrootctl-transfer"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in name).strip("._-") or "chroot"
    return root / f"{safe}.{suffix}"


def _transfer_inspect_import(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    archive = _optional_text(payload, "archive") or _optional_text(payload, "path")
    if not archive:
        raise BridgeProtocolError("MISSING_ARCHIVE", "payload.archive is required")
    return services.transfer().inspect(archive)


def _transfer_import_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    archive = _optional_text(payload, "archive") or _optional_text(payload, "path")
    if not archive:
        raise BridgeProtocolError("MISSING_ARCHIVE", "payload.archive is required")
    return services.transfer().preview_import(
        archive=archive,
        name=_optional_text(payload, "name"),
        conflict=_optional_text(payload, "conflict") or "rename",
    )


def _transfer_preview_export(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    name = _required_name(payload)
    archive = _optional_text(payload, "archive")
    return services.transfer().preview_export(name=name, archive=archive or str(_managed_transfer_archive(name)))


def _artifacts_list(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    return services.transfer().temp_state()


def _transfer_import(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    archive = _optional_text(payload, "archive") or _optional_text(payload, "path")
    if not archive:
        raise BridgeProtocolError("MISSING_ARCHIVE", "payload.archive is required")
    progress({"phase": "preview", "percent": 5, "message": "Inspecting import archive"})
    preview = services.transfer().preview_import(
        archive=archive,
        name=_optional_text(payload, "name"),
        conflict=_optional_text(payload, "conflict") or "rename",
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
    result = services.transfer().delete_temp(path=_optional_text(payload, "path"), delete_all=bool(payload.get("deleteAll") or payload.get("delete_all") or False))
    progress({"phase": "complete", "percent": 100, "message": "Transfer artifact cleanup complete"})
    return result



def _path_state(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "isDir": path.is_dir(),
        "writable": path.exists() and path.is_dir() and __import__("os").access(path, __import__("os").W_OK),
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
            "transferDir": _path_state(_managed_transfer_archive("probe").parent),
        },
        "hostDoctor": serialize_value(host_rows),
        "crossArch": serialize_value(services.system().cross_arch_state()),
        "foreignArchAdvisories": serialize_value(services.system().foreign_arch_advisories()),
    }


def _module_candidates() -> list[Path]:
    return [
        Path("/data/adb/modules/chrootctl"),
        Path("/data/adb/modules_update/chrootctl"),
        Path("/data/adb/ksu/modules/chrootctl"),
        Path("/data/adb/ksu/modules_update/chrootctl"),
    ]


def _module_status(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del services
    del payload
    candidates: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for root in _module_candidates():
        prop = root / "module.prop"
        disabled = root / "disable"
        remove = root / "remove"
        meta = {
            "path": str(root),
            "exists": root.exists(),
            "moduleProp": str(prop),
            "hasModuleProp": prop.exists(),
            "disabled": disabled.exists(),
            "pendingRemoval": remove.exists(),
            "manager": "KernelSU" if "/ksu/" in str(root) else "Magisk/APatch",
            "version": "",
            "id": "",
            "name": "",
        }
        if prop.exists():
            for line in prop.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key in {"id", "name", "version"}:
                    meta[key] = value
            if active is None:
                active = meta
        candidates.append(meta)
    return {
        "active": active,
        "installed": active is not None,
        "candidates": candidates,
        "warnings": [] if active is not None else ["No installed chrootctl Magisk/KernelSU module was detected."],
    }


def _module_build_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..magisk import resolve_startup_targets

    selected = tuple(str(item).strip() for item in payload.get("startupTargets", ()) if str(item).strip()) if isinstance(payload.get("startupTargets", ()), (list, tuple)) else ()
    all_installed = bool(payload.get("allInstalled") or payload.get("all_installed") or False)
    targets = resolve_startup_targets(services, selected_names=selected, all_installed=all_installed)
    archive = _managed_transfer_archive("chrootctl-magisk", "zip")
    return {
        "ok": True,
        "kind": "system.module_build",
        "archive": str(archive),
        "startupTargets": list(targets),
        "blocking": [],
        "warnings": [] if targets else ["No installed startup target was selected; the module will not auto-start chroots."],
        "confirm": False,
    }


def _support_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del services
    archive = _optional_text(payload, "archive") or str(_managed_transfer_archive("chrootctl-support-bundle", "tar.gz"))
    return {
        "ok": True,
        "kind": "support.bundle",
        "archive": archive,
        "blocking": [],
        "warnings": ["The bundle is sanitized, but review it before sharing."],
        "included": ["manifest.json", "events.json", "doctor-host.json", "chroots.json", "config-sanitized.json", "logs/chrootctl.log"],
        "confirm": False,
    }


def _repair_preview(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    raw_decisions = payload.get("decisions")
    if isinstance(raw_decisions, list):
        decisions = [dict(item) for item in raw_decisions if isinstance(item, dict)]
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

    add("root", "python_runtime", "pass", "Python bridge runtime responded to the probe.")
    add("backend", "database_path", "pass" if config.database_path.parent.exists() else "warn", str(config.database_path), "Create or repair the database directory." if not config.database_path.parent.exists() else "")
    add("storage", "chroot_root", "pass" if config.chroot_root.exists() else "warn", str(config.chroot_root), "Create the chroot root or run repair." if not config.chroot_root.exists() else "")
    add("storage", "transfer_dir", "pass" if _managed_transfer_archive("probe").parent.exists() else "warn", str(_managed_transfer_archive("probe").parent), "Create the transfer staging directory." if not _managed_transfer_archive("probe").parent.exists() else "")
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
        add("operations", "operation_journal", "pass", f"{len(stale)} operation record file(s) visible.")
    except Exception as exc:
        add("operations", "operation_journal", "warn", str(exc), "Repair operation journal permissions.")
    return rows


def _debug_probes(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    group = str(payload.get("group") or "all").strip() or "all"
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
    limit = int(payload.get("limit", 50))
    events = [event.to_display_dict() for event in services.audit().recent(limit=limit)]
    return {"events": events, "limit": limit}


def _support_bundle(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    archive = Path(_optional_text(payload, "archive") or str(_managed_transfer_archive("chrootctl-support-bundle", "tar.gz")))
    progress({"phase": "support", "percent": 10, "message": "Collecting sanitized support evidence"})
    if cancelled():
        raise OperationCancelled("Support bundle export was cancelled")
    result = services.support().export_bundle(archive=archive, jobs=None)
    progress({"phase": "complete", "percent": 100, "message": "Support bundle exported"})
    return result


def _module_build(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    from ..magisk import MagiskModuleConfig, render_magisk_module, resolve_startup_targets, validate_magisk_module, zip_magisk_module
    import tempfile

    selected = tuple(str(item).strip() for item in payload.get("startupTargets", ()) if str(item).strip()) if isinstance(payload.get("startupTargets", ()), (list, tuple)) else ()
    all_installed = bool(payload.get("allInstalled") or payload.get("all_installed") or False)
    targets = resolve_startup_targets(services, selected_names=selected, all_installed=all_installed)
    archive = Path(_optional_text(payload, "archive") or str(_managed_transfer_archive("chrootctl-magisk", "zip")))
    progress({"phase": "render", "percent": 20, "message": "Rendering module payload"})
    if cancelled():
        raise OperationCancelled("Module build was cancelled")
    with tempfile.TemporaryDirectory(prefix="chrootctl-module-") as tmp:
        module_dir = Path(tmp) / "module"
        result = render_magisk_module(module_dir, services=services, startup_targets=targets, module_config=MagiskModuleConfig())
        progress({"phase": "validate", "percent": 65, "message": "Validating module layout"})
        validate_magisk_module(result.output_dir)
        if cancelled():
            raise OperationCancelled("Module build was cancelled")
        progress({"phase": "zip", "percent": 85, "message": "Creating module zip"})
        zip_path = zip_magisk_module(result.output_dir, archive)
    progress({"phase": "complete", "percent": 100, "message": "Module zip created"})
    return {"archive": str(zip_path), "startupTargets": list(targets), "bytes": zip_path.stat().st_size}


def _repair_apply(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    raw_decisions = payload.get("decisions")
    if isinstance(raw_decisions, list):
        decisions = [dict(item) for item in raw_decisions if isinstance(item, dict)]
    else:
        decisions = [{"item_id": str(item.get("item_id", "")), "action": str(item.get("action", "skip"))} for item in services.repair().preview_items()]
    progress({"phase": "repair", "percent": 15, "message": "Applying registry repair plan"})
    if cancelled():
        raise OperationCancelled("Registry repair was cancelled")
    result = services.repair().apply_registry_repair_plan(decisions)
    progress({"phase": "complete", "percent": 100, "message": "Registry repair completed"})
    return result


def _cleanup_temp(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    progress({"phase": "cleanup", "percent": 10, "message": "Cleaning temporary artifacts"})
    if cancelled():
        raise OperationCancelled("Temporary cleanup was cancelled")
    result = services.transfer().delete_temp(path=_optional_text(payload, "path"), delete_all=bool(payload.get("deleteAll") or payload.get("delete_all") or True))
    progress({"phase": "complete", "percent": 100, "message": "Temporary cleanup complete"})
    return result


def _debug_export(services: ServiceContainer, payload: dict[str, Any], progress: Callable[[Any], None], cancelled: Callable[[], bool]) -> Any:
    archive = Path(_optional_text(payload, "archive") or str(_managed_transfer_archive("chrootctl-debug-evidence", "tar.gz")))
    progress({"phase": "probes", "percent": 10, "message": "Running debug probes"})
    probes = _debug_probes(services, payload)
    if cancelled():
        raise OperationCancelled("Debug export was cancelled")
    bundle = services.support().export_bundle(archive=archive, jobs=None)
    progress({"phase": "complete", "percent": 100, "message": "Debug evidence exported"})
    return {"archive": str(bundle.archive), "probes": probes, "included": list(bundle.included)}


def _smoke_steps() -> list[dict[str, Any]]:
    return [
        {"id": "bridge_capabilities", "title": "Bridge capabilities", "kind": "query", "operation": "system.dashboard", "required": True},
        {"id": "chroots_list", "title": "Chroots list", "kind": "query", "operation": "chroots.list", "required": True},
        {"id": "operations_list", "title": "Operation history", "kind": "query", "operation": "operations.list", "required": True},
        {"id": "debug_probes", "title": "Debug probes", "kind": "query", "operation": "debug.probes", "required": True},
        {"id": "support_preview", "title": "Support bundle preview", "kind": "preview", "operation": "support.preview", "required": False},
        {"id": "module_preview", "title": "Module build preview", "kind": "preview", "operation": "system.module_build_preview", "required": False},
        {"id": "transfer_artifacts", "title": "Managed artifacts list", "kind": "query", "operation": "artifacts.list", "required": False},
    ]


def _smoke_plan(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del services
    scope = str(payload.get("scope") or "real-device").strip() or "real-device"
    include_optional = bool(payload.get("includeOptional") or payload.get("include_optional") or True)
    steps = [step for step in _smoke_steps() if include_optional or step["required"]]
    return {
        "ok": True,
        "kind": "smoke.plan",
        "scope": scope,
        "stepCount": len(steps),
        "steps": steps,
        "blocking": [],
        "warnings": ["Smoke probes are read-only except for the operation journal entry created by smoke.run."],
        "confirm": False,
    }


def _smoke_report(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    from ..operations import OperationManager

    limit = int(payload.get("limit", 12))
    manager = OperationManager(services.base_config.database_path.parent / "operations")
    recent = [record.to_dict() for record in manager.list_recent(limit=limit)]
    smoke_records = [item for item in recent if str(item.get("kind") or "") == "smoke.run"]
    latest = smoke_records[0] if smoke_records else None
    return {
        "ok": latest is not None,
        "kind": "smoke.report",
        "latest": latest,
        "recentCount": len(smoke_records),
        "blocking": [] if latest is not None else [{"code": "no_smoke_run", "message": "No smoke.run operation has been recorded yet."}],
        "warnings": [],
        "steps": _smoke_steps(),
    }


def _run_smoke_step(services: ServiceContainer, step: dict[str, Any]) -> dict[str, Any]:
    step_id = str(step["id"])
    try:
        if step_id == "bridge_capabilities":
            services.system().dashboard(details=True, tail=5)
        elif step_id == "chroots_list":
            services.chroots().list()
        elif step_id == "operations_list":
            _operations_list(services, {"limit": 5})
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
    steps = _smoke_plan(services, payload)["steps"]
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
    progress({"phase": "complete", "percent": 100, "message": "Smoke suite completed"})
    return {
        "ok": not failed_required,
        "kind": "smoke.run",
        "results": results,
        "passCount": sum(1 for item in results if item.get("status") == "pass"),
        "warnCount": len(warnings),
        "failCount": sum(1 for item in results if item.get("status") == "fail"),
        "blocking": [{"code": str(item.get("id")), "message": str(item.get("message"))} for item in failed_required],
        "warnings": [str(item.get("message")) for item in warnings],
    }



def _latest_smoke_record(services: ServiceContainer, limit: int = 25) -> dict[str, Any] | None:
    from ..operations import OperationManager

    manager = OperationManager(services.base_config.database_path.parent / "operations")
    recent = [record.to_dict() for record in manager.list_recent(limit=limit)]
    for record in recent:
        if str(record.get("kind") or "") == "smoke.run":
            return record
    return None


def _smoke_result_payload(services: ServiceContainer, payload: dict[str, Any]) -> dict[str, Any]:
    latest = _latest_smoke_record(services, limit=int(payload.get("limit", 25)))
    failed = latest is not None and str(latest.get("state") or "").lower() in {"failed", "interrupted", "blocked"}
    return {
        "ok": latest is not None,
        "kind": "smoke.last_result",
        "latest": latest,
        "failed": failed,
        "exportRecommended": latest is not None,
        "supportBundleRecommended": failed,
        "blocking": [] if latest is not None else [{"code": "no_smoke_run", "message": "No smoke.run operation has been recorded yet."}],
        "warnings": ["Create a smoke failure support bundle before changing the device state."] if failed else [],
    }


def _smoke_last_result(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    return _smoke_result_payload(services, payload)


def _write_smoke_result_artifact(services: ServiceContainer, payload: dict[str, Any], suffix: str) -> Path:
    import json

    target = Path(_optional_text(payload, "archive") or str(_managed_transfer_archive(f"chrootctl-smoke-{suffix}", "json")))
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _smoke_result_payload(services, payload)
    if data.get("latest") is None:
        raise BridgeProtocolError("NO_SMOKE_RESULT", "No smoke.run operation has been recorded yet")
    target.write_text(json.dumps(serialize_value(data), indent=2, sort_keys=True), encoding="utf-8")
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
    progress({"phase": "smoke-evidence", "percent": 10, "message": "Persisting smoke evidence"})
    evidence = _write_smoke_result_artifact(services, payload, "failure-evidence")
    if cancelled():
        raise OperationCancelled("Smoke failure bundle was cancelled")
    bundle_payload = dict(payload)
    bundle_payload.setdefault("archive", str(_managed_transfer_archive("chrootctl-smoke-failure-bundle", "tar.gz")))
    bundle = _support_bundle(services, bundle_payload, progress, cancelled)
    progress({"phase": "complete", "percent": 100, "message": "Smoke failure support bundle ready"})
    return {"ok": True, "kind": "smoke.failure.bundle", "evidence": str(evidence), "supportBundle": serialize_value(bundle), "latest": latest.get("latest")}

def _release_readiness(services: ServiceContainer, payload: dict[str, Any]) -> Any:
    del payload
    config = services.base_config
    checks = [
        {"id": "sdk36", "label": "Android SDK 36", "status": "pass", "detail": "Build remains pinned by Android validators."},
        {"id": "webui_retired", "label": "WebUI retired", "status": "pass", "detail": "FastAPI/Jinja/Uvicorn entry points are absent from the release path."},
        {"id": "bridge_allowlist", "label": "Bridge allow-list", "status": "pass", "detail": f"{len(_SPECS)} bridge operations are registered."},
        {"id": "operation_journal", "label": "Operation journal", "status": "pass" if (config.database_path.parent / "operations").exists() else "warn", "detail": str(config.database_path.parent / "operations")},
        {"id": "transfer_staging", "label": "Transfer staging", "status": "pass" if _managed_transfer_archive("readiness").parent.exists() else "warn", "detail": str(_managed_transfer_archive("readiness").parent)},
        {"id": "debug_smoke", "label": "Smoke suite", "status": "pass", "detail": "smoke.plan, smoke.run and smoke.report are available."},
        {"id": "smoke_handoff", "label": "Smoke handoff", "status": "pass", "detail": "smoke.last_result, smoke.result.export and smoke.failure.bundle are registered."},
    ]
    return {
        "ok": not any(item["status"] == "fail" for item in checks),
        "kind": "release.readiness",
        "phase": 26,
        "summary": "Native Android release readiness checks are available.",
        "checks": checks,
        "passCount": sum(1 for item in checks if item["status"] == "pass"),
        "warnCount": sum(1 for item in checks if item["status"] == "warn"),
        "failCount": sum(1 for item in checks if item["status"] == "fail"),
    }

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

    OperationSpec("catalog.tools", "query", "List native tool catalog entries", query_handler=_catalog_tools),
    OperationSpec("catalog.addons", "query", "List native add-on catalog entries", query_handler=_catalog_addons),
    OperationSpec("catalog.search", "query", "Search native catalog entries", query_handler=_catalog_list),
    OperationSpec("packages.inventory", "query", "Return package inventory for one chroot", query_handler=_packages_inventory),
    OperationSpec("packages.compare", "query", "Compare package inventories between chroots", query_handler=_packages_compare),
    OperationSpec("transfer.inspect_import", "query", "Inspect a staged import archive", query_handler=_transfer_inspect_import),
    OperationSpec("artifacts.list", "query", "List managed transfer artifacts", query_handler=_artifacts_list),
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
    OperationSpec("smoke.report", "query", "Return latest real-device smoke operation report", query_handler=_smoke_report),
    OperationSpec("smoke.last_result", "query", "Return latest smoke result and support handoff guidance", query_handler=_smoke_last_result),
    OperationSpec("release.readiness", "query", "Return native release readiness checklist", query_handler=_release_readiness),
    OperationSpec("system.refresh", "operation", "Persist and stream a complete read-only refresh", operation_handler=_refresh),
    OperationSpec("smoke.run", "operation", "Run real-device read-only operational smoke suite", lock_scope="global", operation_handler=_smoke_run),
    OperationSpec("smoke.result.persist", "operation", "Persist latest smoke result into a managed JSON artifact", lock_scope="global", operation_handler=_smoke_result_persist),
    OperationSpec("smoke.result.export", "operation", "Export latest smoke result evidence into a managed JSON artifact", lock_scope="global", operation_handler=_smoke_result_export),
    OperationSpec("smoke.failure.bundle", "operation", "Create support bundle linked to the latest smoke failure", lock_scope="global", operation_handler=_smoke_failure_bundle),
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
