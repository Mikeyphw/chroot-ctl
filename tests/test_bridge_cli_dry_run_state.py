from __future__ import annotations

import json
from pathlib import Path

from chrootctl.bridge import cli as bridge_cli
from chrootctl.bridge.dispatcher import BridgeDispatcher
from chrootctl.bridge.protocol import BridgeRequest
from chrootctl.services import create_service_container


def test_implicit_dry_run_uses_isolated_state_when_default_is_unusable(monkeypatch) -> None:
    monkeypatch.setattr(bridge_cli, "_default_bridge_state_usable", lambda: False)
    config_path, owner = bridge_cli._effective_service_config(None, dry_run=True)
    assert config_path is not None
    assert owner is not None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        root = Path(owner.name)
        assert Path(payload["database_path"]).parent == root
        assert Path(payload["snapshot_dir"]).parent == root
        assert Path(payload["log_file"]).parent == root

        services = create_service_container(config_path, dry_run=True)
        response = BridgeDispatcher(services).query(
            BridgeRequest.from_mapping(
                {
                    "protocolVersion": 1,
                    "requestId": "test",
                    "operation": "operations.list",
                    "payload": {},
                }
            )
        )
        assert response.ok is True
        assert response.data == []
    finally:
        owner.cleanup()


def test_explicit_config_is_never_replaced_by_dry_run(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(bridge_cli, "_default_bridge_state_usable", lambda: False)
    effective, owner = bridge_cli._effective_service_config(config_path, dry_run=True)
    assert effective == config_path
    assert owner is None
