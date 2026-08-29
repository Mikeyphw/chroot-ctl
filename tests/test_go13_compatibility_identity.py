from __future__ import annotations

import json
from pathlib import Path

from chrootctl.magisk import MagiskModuleConfig, _compatibility_manifest_payload
from chrootctl.release_parity import COMPATIBILITY_SCHEMA_VERSION


def test_schema3_manifest_is_generic_go_backend() -> None:
    payload = _compatibility_manifest_payload(MagiskModuleConfig())
    assert COMPATIBILITY_SCHEMA_VERSION == 3
    assert payload["schemaVersion"] == 3
    assert "pythonPackage" not in payload
    assert payload["backend"] == {"implementation": "go", "version": "0.11.0"}
    assert payload["nativeRuntime"] == {"schemaVersion": 2, "kind": "go-native", "platform": "android", "abi": "arm64-v8a", "entrypoint": "chrootctl"}
    assert payload["bridgeProtocolVersion"] == 1


def test_runtime_resolver_go14_removes_python_schema_fallback() -> None:
    text = Path("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt").read_text()
    assert "COMPATIBILITY_SCHEMA_VERSION = 3" in text
    assert "LEGACY_COMPATIBILITY_SCHEMA_VERSION" not in text
    assert 'EXPECTED_BACKEND_IMPLEMENTATION = "go"' in text
    assert 'NATIVE_RUNTIME_KIND = "go-native"' in text
    assert 'LEGACY_NATIVE_RUNTIME_KIND' not in text
