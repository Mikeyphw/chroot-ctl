from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chrootctl.bridge.protocol import BridgeProtocolError, BridgeRequest, MAX_BRIDGE_REQUEST_BYTES
from chrootctl.bridge.registry import resolve_spec
from chrootctl.config import ChrootConfig
from chrootctl.validation import no_duplicate_top_level_functions

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def test_lint_contract_keeps_only_old_target_api_suppression() -> None:
    lint = (ROOT / "android/app/lint.xml").read_text(encoding="utf-8")
    assert 'id="OldTargetApi"' in lint
    assert "GradleDependency" not in lint
    assert "NewerVersionAvailable" not in lint
    assert "UnusedResources" not in lint
    assert "PluralsCandidate" not in lint


def test_source_tree_contains_no_backup_artifacts_or_duplicate_functions() -> None:
    forbidden: list[str] = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if "dist" in rel.parts:
            continue
        if path.name.endswith((".bak", ".orig", ".rej", "~")) or ".bak-" in path.name:
            forbidden.append(str(rel))
    assert forbidden == []
    assert no_duplicate_top_level_functions((SRC / "chrootctl").rglob("*.py")) == {}


def test_config_rejects_mount_escape_and_string_booleans(tmp_path: Path) -> None:
    bad_mount = tmp_path / "bad-mount.json"
    bad_mount.write_text(json.dumps({"media_mounts": {"/sdcard": "../escape"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="must not contain"):
        ChrootConfig.load(bad_mount)

    bad_bool = tmp_path / "bad-bool.json"
    bad_bool.write_text(json.dumps({"mount_data_with_dev_suid": "false"}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON boolean"):
        ChrootConfig.load(bad_bool)


def test_config_for_chroot_rejects_path_names() -> None:
    with pytest.raises(ValueError, match="safe basename"):
        ChrootConfig().for_chroot("../bad")


def test_bridge_rejects_oversized_and_unknown_request_fields() -> None:
    with pytest.raises(BridgeProtocolError, match="unknown top-level"):
        BridgeRequest.from_mapping(
            {"protocolVersion": 1, "requestId": "r1", "operation": "chroots.list", "payload": {}, "extra": True}
        )
    raw = json.dumps({"protocolVersion": 1, "requestId": "r1", "operation": "chroots.list", "payload": {"blob": "x" * MAX_BRIDGE_REQUEST_BYTES}})
    with pytest.raises(BridgeProtocolError, match="exceed"):
        BridgeRequest.from_json(raw)


def test_bridge_cli_preserves_request_id_on_parse_failure() -> None:
    request = json.dumps({"protocolVersion": 999, "requestId": "android-123", "operation": "chroots.list", "payload": {}})
    completed = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "query", "--request-file", "-"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        input=request,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["requestId"] == "android-123"


def test_bridge_rejects_unknown_payload_field_and_string_boolean() -> None:
    request = BridgeRequest.from_mapping(
        {"protocolVersion": 1, "requestId": "r1", "operation": "system.dashboard", "payload": {"details": True, "surprise": 1}}
    )
    with pytest.raises(BridgeProtocolError, match="Unsupported field"):
        resolve_spec(request, "query")

    request = BridgeRequest.from_mapping(
        {"protocolVersion": 1, "requestId": "r2", "operation": "users.set_sudo", "payload": {"name": "androidos", "username": "mike", "enabled": "false"}}
    )
    resolve_spec(request, "operation")
    from chrootctl.bridge.registry import _payload_bool

    with pytest.raises(BridgeProtocolError, match="JSON boolean"):
        _payload_bool(request.payload, "enabled")


def test_service_container_validates_name_and_username_before_runtime_paths() -> None:
    from chrootctl.services.context import ServiceContainer
    from chrootctl.registry import ChrootRegistry

    container = ServiceContainer(ChrootConfig(), ChrootRegistry(ChrootConfig().database_path), logger=None)
    with pytest.raises(ValueError, match="safe basename"):
        container.config_for("../bad")
    with pytest.raises(ValueError, match="invalid username"):
        container.config_for("androidos", username="bad user")


def test_lifecycle_bridge_booleans_are_strict_json_booleans() -> None:
    from chrootctl.bridge.registry import _start_chroot

    class Dummy:
        def start(self, name: str, *, login: bool = True, root_login: bool = False):
            return {"name": name, "login": login, "rootLogin": root_login}

    class Services:
        def chroots(self):
            return Dummy()

    with pytest.raises(BridgeProtocolError, match="JSON boolean"):
        _start_chroot(Services(), {"name": "androidos", "login": "false"}, lambda event: None, lambda: False)


def test_smoke_plan_fields_are_allowlisted_and_strict() -> None:
    request = BridgeRequest.from_mapping(
        {
            "protocolVersion": 1,
            "requestId": "r-smoke",
            "operation": "smoke.plan",
            "payload": {"name": "androidos", "target": "androidos", "scope": "real-device", "includeOptional": False},
        }
    )
    resolve_spec(request, "query")

    request = BridgeRequest.from_mapping(
        {
            "protocolVersion": 1,
            "requestId": "r-smoke-bad",
            "operation": "smoke.plan",
            "payload": {"includeOptional": "false"},
        }
    )
    resolve_spec(request, "query")
    from chrootctl.bridge.registry import _smoke_plan

    class Services:
        def chroots(self):
            raise AssertionError("should not reach service discovery for invalid boolean")

    with pytest.raises(BridgeProtocolError, match="JSON boolean"):
        _smoke_plan(Services(), request.payload)


def test_bridge_failure_messages_redact_secret_assignments() -> None:
    from chrootctl.bridge.protocol import BridgeResponse

    message = BridgeResponse.failure("r", Exception("password=secret token:abc -pass pass:hunter2")).to_dict()["error"]["message"]
    assert "secret" not in message
    assert "abc" not in message
    assert "hunter2" not in message
    assert "<redacted>" in message

def test_source_hygiene_allows_git_metadata(monkeypatch, tmp_path: Path) -> None:
    import manage_source

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (tmp_path / "src" / "chrootctl").mkdir(parents=True)
    (tmp_path / "src" / "chrootctl" / "sample.py").write_text(
        "def ok():\n    return True\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(manage_source, "ROOT", tmp_path)
    manage_source._validate_source_hygiene()

