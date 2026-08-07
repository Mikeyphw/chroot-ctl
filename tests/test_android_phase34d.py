from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def test_phase34d_capabilities_command_is_service_free() -> None:
    bridge_cli = read("src/chrootctl/bridge/cli.py")
    top_level = bridge_cli.split("def main", 1)[0]
    assert "from ..services import create_service_container" not in top_level
    assert "from .dispatcher import BridgeDispatcher" not in top_level
    assert bridge_cli.find('if args.command == "capabilities"') < bridge_cli.find("from ..services import create_service_container")
    assert "_capabilities_response" in bridge_cli
    assert "runtimeHealth" in bridge_cli
    assert "CAPABILITIES_PARTIAL" in bridge_cli


def test_phase34d_capabilities_still_exposes_protocol_when_services_are_broken() -> None:
    script = textwrap.dedent(
        """
        import importlib.abc
        import json
        import sys

        class BlockServices(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "chrootctl.services" or fullname.startswith("chrootctl.services."):
                    raise RuntimeError("services intentionally unavailable")
                return None

        sys.meta_path.insert(0, BlockServices())
        from chrootctl.bridge.cli import main
        raise SystemExit(main(["capabilities"]))
        """
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["protocolVersion"] == 1
    assert payload["requestId"] == "capabilities"
    assert payload["ok"] is True
    assert payload["data"]["protocolVersion"] == 1
    assert payload["data"]["transport"] == ["json", "ndjson"]
    assert payload["data"]["arbitraryShell"] is False
    assert payload["data"]["runtimeHealth"]["status"] == "degraded"
    assert payload["data"]["runtimeHealth"]["code"] == "CAPABILITIES_PARTIAL"
    assert payload["warnings"]


def test_phase34d_android_resolver_protocol_probe_remains_in_place() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert 'listOf("capabilities")' in resolver
    assert 'data.optInt("protocolVersion", -1) == BRIDGE_PROTOCOL_VERSION' in resolver
    assert 'envelope.optBoolean("ok")' in resolver
    assert "/data/adb/modules/chrootctl-magisk/system/bin/chrootctl" in read("docs/android/PHASE_34D_PROTOCOL_CAPABILITIES_PROBE.md")


def test_phase34d_api36_and_strict_lint_policy_are_preserved() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    assert "compileSdk = 36" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"\s*/>', lint)
    assert ignored == ["OldTargetApi"]
