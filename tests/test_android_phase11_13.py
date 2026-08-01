from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "kotlin" / "com" / "mikeyphw" / "chrootctl"


def _bridge(command: str, operation: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    request = json.dumps({"protocolVersion": 1, "requestId": "test", "operation": operation, "payload": payload or {}})
    completed = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "--dry-run", command, "--request-file", "-"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        input=request,
        text=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.stdout.strip(), completed.stderr
    return json.loads(completed.stdout)


def test_phase11_install_bridge_contracts_are_allowlisted() -> None:
    capabilities = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "--dry-run", "capabilities"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    names = {item["name"] for item in json.loads(capabilities.stdout)["data"]["operations"]}
    assert {"install.form", "install.preview", "install.run"}.issubset(names)
    form = _bridge("query", "install.form", {})
    assert form["ok"] is True
    assert "defaults" in form["data"]
    preview = _bridge("preview", "install.preview", {"distro": "ubuntu", "name": "androidos", "username": "mike", "profile": "minimal", "desktop": "none"})
    assert preview["ok"] is True
    assert preview["data"]["ok"] is True


def test_phase12_lifecycle_bridge_contracts_are_allowlisted() -> None:
    registry = (SRC / "chrootctl" / "bridge" / "registry.py").read_text(encoding="utf-8")
    assert 'OperationSpec("chroots.lifecycle.preview"' in registry
    assert 'OperationSpec("chroots.start"' in registry
    assert 'OperationSpec("chroots.restart"' in registry
    assert 'OperationSpec("chroots.remove.execute"' in registry
    assert 'payload.confirmation must match payload.name' in registry


def test_phase13_snapshot_bridge_contracts_are_allowlisted() -> None:
    response = _bridge("query", "snapshots.list", {})
    assert response["ok"] is True
    registry = (SRC / "chrootctl" / "bridge" / "registry.py").read_text(encoding="utf-8")
    assert 'OperationSpec("snapshots.preview"' in registry
    assert 'OperationSpec("snapshots.create"' in registry
    assert 'OperationSpec("snapshots.restore"' in registry
    assert 'OperationSpec("snapshots.export"' in registry


def test_android_phase11_13_native_screens_are_wired() -> None:
    app = (ANDROID / "ui" / "ChrootCtlApp.kt").read_text(encoding="utf-8")
    install = (ANDROID / "ui" / "install" / "InstallScreen.kt").read_text(encoding="utf-8")
    chroots = (ANDROID / "ui" / "chroots" / "ChrootsScreen.kt").read_text(encoding="utf-8")
    service = (ANDROID / "operations" / "ChrootOperationService.kt").read_text(encoding="utf-8")
    assert "AppDestination.Install" in app
    assert "InstallScreen" in app
    assert "install.run" in app
    assert "InstallDraft" in install
    assert "PreviewCard" in install
    assert "LifecyclePanel" in chroots
    assert "SnapshotPanel" in chroots
    assert "onExecuteRemove" in chroots
    assert "onStartSnapshotRestore" in chroots
    assert "onStartSnapshotExport" in chroots
    assert "chroots.remove.execute" in app
    assert "snapshots.restore" in app
    assert "snapshots.export" in app
    assert "ACTION_BRIDGE_OPERATION" in service
    assert "startBridgeOperation" in service
    assert "runShell" not in app + install + chroots + service


def test_android_phase11_13_ui_closes_destructive_caveats() -> None:
    view_model = (ANDROID / "ui" / "MainViewModel.kt").read_text(encoding="utf-8")
    chroots = (ANDROID / "ui" / "chroots" / "ChrootsScreen.kt").read_text(encoding="utf-8")
    strings = (ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    assert "removePayloadJson" in view_model
    assert "snapshotRestorePayloadJson" in view_model
    assert "snapshotExportPayloadJson" in view_model
    assert "previewSnapshotAction" in view_model
    assert "confirmation" in view_model
    assert "OutlinedTextField" in chroots
    assert "onExecuteRemove" in chroots
    assert "onStartSnapshotRestore" in chroots
    assert "onStartSnapshotExport" in chroots
    assert "action_remove_chroot" in strings
    assert "action_restore_snapshot" in strings
    assert "action_export_snapshot" in strings
