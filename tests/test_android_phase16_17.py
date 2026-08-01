from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "kotlin" / "com" / "mikeyphw" / "chrootctl"


def _capability_names() -> set[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "--dry-run", "capabilities"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    return {item["name"] for item in json.loads(completed.stdout)["data"]["operations"]}


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


def test_phase16_catalog_package_bridge_contracts_are_allowlisted() -> None:
    names = _capability_names()
    assert {
        "catalog.tools",
        "catalog.addons",
        "catalog.search",
        "catalog.preview",
        "catalog.apply",
        "packages.inventory",
        "packages.compare",
    }.issubset(names)
    tools = _bridge("query", "catalog.tools", {"query": "ssh"})
    assert tools["ok"] is True
    assert tools["data"]["kind"] == "tool"
    preview = _bridge("preview", "catalog.preview", {"kind": "tool", "name": "androidos", "names": []})
    assert preview["ok"] is True
    assert preview["data"]["ok"] is False


def test_phase17_transfer_bridge_contracts_are_allowlisted() -> None:
    names = _capability_names()
    assert {
        "transfer.inspect_import",
        "transfer.import",
        "transfer.preview_export",
        "transfer.export",
        "artifacts.list",
        "artifacts.cleanup",
    }.issubset(names)
    artifacts = _bridge("query", "artifacts.list")
    assert artifacts["ok"] is True
    assert "items" in artifacts["data"]


def test_android_phase16_17_native_catalog_transfer_are_wired() -> None:
    app = (ANDROID / "ui" / "ChrootCtlApp.kt").read_text(encoding="utf-8")
    activity = (ANDROID / "MainActivity.kt").read_text(encoding="utf-8")
    view_model = (ANDROID / "ui" / "MainViewModel.kt").read_text(encoding="utf-8")
    tools = (ANDROID / "ui" / "tools" / "ToolsScreen.kt").read_text(encoding="utf-8")
    repository = (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
    models = (ANDROID / "model" / "UiModels.kt").read_text(encoding="utf-8")
    aidl = (ROOT / "android" / "app" / "src" / "main" / "aidl" / "com" / "mikeyphw" / "chrootctl" / "root" / "IChrootRootService.aidl").read_text(encoding="utf-8")
    combined = app + activity + view_model + tools + repository + models + aidl
    for token in (
        "CatalogPane",
        "PackagePane",
        "TransferPane",
        "catalog.apply",
        "packages.inventory",
        "packages.compare",
        "transfer.inspect_import",
        "transfer.import",
        "transfer.export",
        "artifacts.cleanup",
        "ActivityResultContracts.OpenDocument",
        "ActivityResultContracts.CreateDocument",
        "transferFromDescriptor",
        "transferToDescriptor",
    ):
        assert token in combined
    assert "WebView" not in combined
    assert "executeArbitraryCommand" not in combined
    assert "combine(arrayOf" not in combined


def test_phase16_17_validator_and_strings_are_present() -> None:
    strings = (ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate-android-phase16-17.py").read_text(encoding="utf-8")
    for name in (
        "catalog_title",
        "package_title",
        "transfer_title",
        "transfer_pick_import_action",
        "transfer_create_document_action",
        "artifacts_cleanup_action",
    ):
        assert f'name="{name}"' in strings
    assert "Phase 16-17 catalog and transfer validator passed" in validator
