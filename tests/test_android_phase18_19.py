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


def test_phase18_system_support_repair_contracts_are_allowlisted() -> None:
    names = _capability_names()
    assert {
        "system.runtime",
        "system.module_status",
        "system.module_build_preview",
        "system.module_build",
        "support.preview",
        "support.bundle",
        "repair.preview",
        "repair.apply",
        "cleanup.temp_preview",
        "cleanup.temp",
    }.issubset(names)
    runtime = _bridge("query", "system.runtime")
    assert runtime["ok"] is True
    assert "runtime" in runtime["data"]
    support = _bridge("preview", "support.preview")
    assert support["ok"] is True
    assert support["data"]["ok"] is True


def test_phase19_debug_workbench_contracts_are_allowlisted() -> None:
    names = _capability_names()
    assert {"debug.probes", "debug.timeline", "debug.export"}.issubset(names)
    probes = _bridge("query", "debug.probes", {"group": "storage"})
    assert probes["ok"] is True
    assert "probes" in probes["data"]
    timeline = _bridge("query", "debug.timeline")
    assert timeline["ok"] is True
    assert "events" in timeline["data"]


def test_android_phase18_19_system_debug_ui_is_wired() -> None:
    app = (ANDROID / "ui" / "ChrootCtlApp.kt").read_text(encoding="utf-8")
    view_model = (ANDROID / "ui" / "MainViewModel.kt").read_text(encoding="utf-8")
    tools = (ANDROID / "ui" / "tools" / "ToolsScreen.kt").read_text(encoding="utf-8")
    repository = (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
    models = (ANDROID / "model" / "UiModels.kt").read_text(encoding="utf-8")
    combined = app + view_model + tools + repository + models
    for token in (
        "SystemSupportPane",
        "DebugPane",
        "SystemSupportCard",
        "DebugWorkbenchCard",
        "support.bundle",
        "system.module_build",
        "repair.apply",
        "cleanup.temp",
        "debug.export",
        "debug.probes",
        "debug.timeline",
    ):
        assert token in combined
    assert "WebView" not in combined
    assert "executeArbitraryCommand" not in combined
    assert "combine(arrayOf" not in combined


def test_phase18_19_validator_and_strings_are_present() -> None:
    strings = (ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate-android-phase18-19.py").read_text(encoding="utf-8")
    for name in (
        "system_support_body",
        "support_bundle_action",
        "module_build_action",
        "repair_apply_selected_action",
        "debug_timeline_title",
        "debug_export_action",
    ):
        assert f'name="{name}"' in strings
    assert "Phase 18-19 system, support and debug validator passed" in validator
