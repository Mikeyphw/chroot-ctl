from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from chrootctl.bridge.redaction import redact_value

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


def test_phase14_user_bridge_contracts_are_allowlisted() -> None:
    capabilities = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "--dry-run", "capabilities"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    names = {item["name"] for item in json.loads(capabilities.stdout)["data"]["operations"]}
    assert {
        "users.list",
        "users.get",
        "users.preview",
        "users.add",
        "users.remove",
        "users.sync_uid_gid",
        "users.set_shell",
        "users.set_sudo",
        "users.set_password",
    }.issubset(names)
    preview = _bridge("preview", "users.preview", {"name": "androidos", "username": "mike", "action": "set_password"})
    assert preview["ok"] is True
    assert preview["data"]["confirmUsername"] is True


def test_phase14_password_payloads_are_redacted_by_default() -> None:
    assert redact_value({"password": "hunter2", "confirmPassword": "hunter2", "username": "mike"}) == {
        "password": "<redacted>",
        "confirmPassword": "<redacted>",
        "username": "mike",
    }


def test_phase15_service_bridge_contracts_are_allowlisted() -> None:
    capabilities = subprocess.run(
        [sys.executable, "-m", "chrootctl.bridge.cli", "--dry-run", "capabilities"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    names = {item["name"] for item in json.loads(capabilities.stdout)["data"]["operations"]}
    assert {
        "services.list",
        "services.get",
        "services.journal",
        "services.preview",
        "services.start",
        "services.stop",
        "services.restart",
        "services.enable",
        "services.disable",
    }.issubset(names)


def test_android_phase14_15_native_users_and_services_are_wired() -> None:
    app = (ANDROID / "ui" / "ChrootCtlApp.kt").read_text(encoding="utf-8")
    view_model = (ANDROID / "ui" / "MainViewModel.kt").read_text(encoding="utf-8")
    chroots = (ANDROID / "ui" / "chroots" / "ChrootsScreen.kt").read_text(encoding="utf-8")
    repository = (ANDROID / "repository" / "BridgeRepository.kt").read_text(encoding="utf-8")
    models = (ANDROID / "model" / "UiModels.kt").read_text(encoding="utf-8")
    combined = app + view_model + chroots + repository + models
    for token in (
        "UsersPanel",
        "ServicesPanel",
        "UsersPane",
        "ServicesPane",
        "refreshUsers",
        "previewUserAction",
        "previewServiceAction",
        "users.set_password",
        "users.remove",
        "services.restart",
        "services.disable",
        "services.journal",
        "servicePayload",
        "userPayload",
    ):
        assert token in combined
    assert "runShell" not in combined
    assert "executeArbitraryCommand" not in combined
    assert "combine(arrayOf" not in combined


def test_phase14_15_strings_and_validator_are_present() -> None:
    strings = (ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate-android-phase14-15.py").read_text(encoding="utf-8")
    for name in (
        "users_actions_title",
        "action_set_password",
        "action_remove_user",
        "services_actions_title",
        "action_service_journal",
        "action_service_restart",
    ):
        assert f'name="{name}"' in strings
    assert "Phase 14-15 users and services validator passed" in validator
