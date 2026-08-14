from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from .protocol import BridgeProtocolError, serialize_value
from .redaction import redact_value

PREVIEW_SCHEMA_VERSION = 1
PREVIEW_TTL_SECONDS = 15 * 60
_CONTRACT_FIELDS = frozenset({"previewId", "payloadHash", "resourceRevision"})
_UNBOUND_FIELDS = frozenset({
    "action",
    "confirmation",
    "confirmName",
    "confirmUsername",
    "password",
    "confirmPassword",
    "title",
})

PREVIEW_REQUIRED_OPERATIONS = frozenset({
    "install.run",
    "chroots.start",
    "chroots.restart",
    "chroots.upgrade",
    "chroots.remove.execute",
    "snapshots.create",
    "snapshots.restore",
    "snapshots.export",
    "users.add",
    "users.remove",
    "users.sync_uid_gid",
    "users.set_shell",
    "users.set_sudo",
    "users.set_password",
    "services.start",
    "services.stop",
    "services.restart",
    "services.enable",
    "services.disable",
    "smoke.run",
    "catalog.apply",
    "transfer.import",
    "transfer.export",
    "artifacts.cleanup",
    "support.bundle",
    "system.module_build",
    "repair.apply",
    "cleanup.temp",
})


class PreviewContractStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def issue(
        self,
        *,
        preview_operation: str,
        action_operation: str,
        preview_payload: Mapping[str, Any],
        preview_result: Any,
    ) -> dict[str, Any]:
        preview_id = uuid.uuid4().hex
        now = time.time()
        payload_hash = binding_payload_hash(action_operation, preview_payload)
        resource_revision = preview_resource_revision(preview_result)
        record = {
            "schemaVersion": PREVIEW_SCHEMA_VERSION,
            "previewId": preview_id,
            "previewOperation": preview_operation,
            "actionOperation": action_operation,
            "payloadHash": payload_hash,
            "resourceRevision": resource_revision,
            "previewPayload": _safe_payload(preview_payload),
            "createdAt": now,
            "expiresAt": now + PREVIEW_TTL_SECONDS,
        }
        _atomic_json_write(self.root / f"{preview_id}.json", record)
        return {key: record[key] for key in ("previewId", "actionOperation", "payloadHash", "resourceRevision", "expiresAt")}

    def load(self, preview_id: str) -> dict[str, Any]:
        path = self._path_for(preview_id)
        return self._load_path(path)

    def verify_fields(self, action_operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        preview_id = str(payload.get("previewId") or "")
        supplied_hash = str(payload.get("payloadHash") or "")
        supplied_revision = str(payload.get("resourceRevision") or "")
        if not preview_id or not supplied_hash or not supplied_revision:
            raise BridgeProtocolError(
                "PREVIEW_CONTRACT_REQUIRED",
                f"{action_operation} requires previewId, payloadHash, and resourceRevision from a fresh preview",
            )

        source = self._path_for(preview_id)
        claim = self.root / f".{preview_id}.{uuid.uuid4().hex}.claim"
        try:
            os.rename(source, claim)
        except FileNotFoundError as exc:
            raise BridgeProtocolError("PREVIEW_NOT_FOUND", "Preview approval is missing or has already been consumed") from exc
        except OSError as exc:
            raise BridgeProtocolError("PREVIEW_CLAIM_FAILED", "Preview approval could not be claimed safely") from exc

        try:
            record = self._load_path(claim, remove_if_expired=False)
            if record.get("actionOperation") != action_operation:
                raise BridgeProtocolError("PREVIEW_ACTION_MISMATCH", "Preview approval belongs to a different action")
            expected_hash = str(record.get("payloadHash") or "")
            if supplied_hash != expected_hash or binding_payload_hash(action_operation, payload) != expected_hash:
                raise BridgeProtocolError("PREVIEW_PAYLOAD_CHANGED", "Action payload changed after preview; preview again")
            if supplied_revision != str(record.get("resourceRevision") or ""):
                raise BridgeProtocolError("PREVIEW_REVISION_MISMATCH", "Preview resource revision does not match the approved preview")
            return record
        finally:
            claim.unlink(missing_ok=True)

    def _path_for(self, preview_id: str) -> Path:
        if not preview_id or len(preview_id) != 32 or any(char not in "0123456789abcdef" for char in preview_id):
            raise BridgeProtocolError("INVALID_PREVIEW_ID", "payload.previewId is invalid")
        return self.root / f"{preview_id}.json"

    def _load_path(self, path: Path, *, remove_if_expired: bool = True) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise BridgeProtocolError("PREVIEW_NOT_FOUND", "Preview approval is missing or has already been consumed") from exc
        except (OSError, ValueError) as exc:
            raise BridgeProtocolError("PREVIEW_RECORD_INVALID", "Preview approval record is invalid") from exc
        if not isinstance(value, dict):
            raise BridgeProtocolError("PREVIEW_RECORD_INVALID", "Preview approval record is invalid")
        if float(value.get("expiresAt") or 0.0) < time.time():
            if remove_if_expired:
                path.unlink(missing_ok=True)
            raise BridgeProtocolError("PREVIEW_EXPIRED", "Preview approval expired; preview the action again")
        return value


def binding_payload_hash(action_operation: str, payload: Mapping[str, Any]) -> str:
    normalized = {
        str(key): serialize_value(value)
        for key, value in payload.items()
        if key not in _CONTRACT_FIELDS and key not in _UNBOUND_FIELDS
    }
    envelope = {"actionOperation": action_operation, "payload": normalized}
    return _sha256_json(envelope)


def preview_resource_revision(preview_result: Any) -> str:
    value = serialize_value(preview_result)
    if isinstance(value, dict):
        value = {key: item for key, item in value.items() if key not in _CONTRACT_FIELDS and key not in {"expiresAt", "actionOperation"}}
    return _sha256_json(value)


def action_operation_for_preview(preview_operation: str, payload: Mapping[str, Any]) -> str | None:
    if preview_operation == "install.preview":
        return "install.run"
    if preview_operation == "chroots.remove":
        return "chroots.remove.execute"
    if preview_operation == "chroots.lifecycle.preview":
        action = str(payload.get("action") or "").strip()
        return {
            "start": "chroots.start",
            "restart": "chroots.restart",
            "upgrade": "chroots.upgrade",
            "remove": "chroots.remove.execute",
        }.get(action)
    if preview_operation == "snapshots.preview":
        return {
            "create": "snapshots.create",
            "restore": "snapshots.restore",
            "export": "snapshots.export",
        }.get(str(payload.get("action") or "").strip())
    if preview_operation == "users.preview":
        action = str(payload.get("action") or "").strip().replace("-", "_")
        return {
            "add": "users.add",
            "remove": "users.remove",
            "sync_uid_gid": "users.sync_uid_gid",
            "set_shell": "users.set_shell",
            "set_sudo": "users.set_sudo",
            "set_password": "users.set_password",
            "password": "users.set_password",
        }.get(action)
    if preview_operation == "services.preview":
        action = str(payload.get("action") or "").strip()
        return {name: f"services.{name}" for name in ("start", "stop", "restart", "enable", "disable")}.get(action)
    if preview_operation == "smoke.preview":
        return "smoke.run"
    if preview_operation == "catalog.preview":
        return "catalog.apply"
    if preview_operation == "chroots.export":
        return "transfer.export"
    if preview_operation == "transfer.import_preview":
        return "transfer.import"
    if preview_operation == "transfer.preview_export":
        return "transfer.export"
    if preview_operation == "artifacts.cleanup_preview":
        return "artifacts.cleanup"
    if preview_operation == "support.preview":
        return "support.bundle"
    if preview_operation == "system.module_build_preview":
        return "system.module_build"
    if preview_operation == "repair.preview":
        return "repair.apply"
    if preview_operation == "cleanup.temp_preview":
        return "cleanup.temp"
    return None


def preview_payload_for_action(
    action_operation: str,
    payload: Mapping[str, Any],
    *,
    preview_operation: str | None = None,
) -> tuple[str, dict[str, Any]] | None:
    preview_excluded = _CONTRACT_FIELDS | frozenset({"action", "confirmation", "confirmName", "confirmUsername", "title"})
    clean = {str(key): value for key, value in payload.items() if key not in preview_excluded}
    variants: dict[str, dict[str, str | None]] = {
        "chroots.remove.execute": {"chroots.remove": None, "chroots.lifecycle.preview": "remove"},
        "transfer.export": {"transfer.preview_export": None, "chroots.export": None},
    }
    if preview_operation and preview_operation in variants.get(action_operation, {}):
        action = variants[action_operation][preview_operation]
        if action is not None:
            clean["action"] = action
        return preview_operation, clean

    mapping: dict[str, tuple[str, str | None]] = {
        "install.run": ("install.preview", None),
        "chroots.start": ("chroots.lifecycle.preview", "start"),
        "chroots.restart": ("chroots.lifecycle.preview", "restart"),
        "chroots.upgrade": ("chroots.lifecycle.preview", "upgrade"),
        "chroots.remove.execute": ("chroots.remove", None),
        "snapshots.create": ("snapshots.preview", "create"),
        "snapshots.restore": ("snapshots.preview", "restore"),
        "snapshots.export": ("snapshots.preview", "export"),
        "users.add": ("users.preview", "add"),
        "users.remove": ("users.preview", "remove"),
        "users.sync_uid_gid": ("users.preview", "sync_uid_gid"),
        "users.set_shell": ("users.preview", "set_shell"),
        "users.set_sudo": ("users.preview", "set_sudo"),
        "users.set_password": ("users.preview", "set_password"),
        "services.start": ("services.preview", "start"),
        "services.stop": ("services.preview", "stop"),
        "services.restart": ("services.preview", "restart"),
        "services.enable": ("services.preview", "enable"),
        "services.disable": ("services.preview", "disable"),
        "smoke.run": ("smoke.preview", None),
        "catalog.apply": ("catalog.preview", None),
        "transfer.import": ("transfer.import_preview", None),
        "transfer.export": ("transfer.preview_export", None),
        "artifacts.cleanup": ("artifacts.cleanup_preview", None),
        "support.bundle": ("support.preview", None),
        "system.module_build": ("system.module_build_preview", None),
        "repair.apply": ("repair.preview", None),
        "cleanup.temp": ("cleanup.temp_preview", None),
    }
    target = mapping.get(action_operation)
    if target is None:
        return None
    preview_operation, action = target
    if action is not None:
        clean["action"] = action
    return preview_operation, clean


def _safe_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted = redact_value({str(key): serialize_value(value) for key, value in payload.items()})
    return dict(redacted) if isinstance(redacted, dict) else {}


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
