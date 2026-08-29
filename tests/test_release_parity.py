from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrootctl.native_runtime import DEFAULT_NATIVE_RUNTIME_BUILD_ROOT, NATIVE_RUNTIME_KIND, NATIVE_RUNTIME_SCHEMA_VERSION
from chrootctl.release_parity import (
    check_release_parity,
    expected_compatibility_manifest,
    expected_runtime_resolver_constants,
)


def test_android_runtime_resolver_matches_module_and_native_runtime_constants() -> None:
    result = check_release_parity(Path.cwd())
    assert result.ok, result.mismatches
    assert "RuntimeResolver.kt:BRIDGE_PROTOCOL_VERSION" in result.checked
    assert "docs/release/compatibility-manifest.json" in result.checked


def test_expected_compatibility_manifest_matches_release_identity() -> None:
    payload = expected_compatibility_manifest()
    assert payload["schemaVersion"] == 2
    assert payload["project"] == "chrootctl"
    assert payload["module"]["id"] == "chrootctl-magisk"  # type: ignore[index]
    assert payload["nativeRuntime"] if "nativeRuntime" in payload else True
    checked_in = json.loads(Path("docs/release/compatibility-manifest.json").read_text(encoding="utf-8"))
    assert checked_in == payload


def test_runtime_resolver_mismatch_is_reported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    resolver = repo / "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt"
    resolver.parent.mkdir(parents=True)
    constants = expected_runtime_resolver_constants()
    constants["EXPECTED_MODULE_VERSION"] = "broken"
    resolver.write_text("\n".join(f'private const val {k} = {json.dumps(v)}' for k, v in constants.items()), encoding="utf-8")
    manifest = repo / "docs/release/compatibility-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(expected_compatibility_manifest()), encoding="utf-8")

    result = check_release_parity(repo)
    assert result.ok is False
    assert any("EXPECTED_MODULE_VERSION" in item for item in result.mismatches)


def test_go_native_runtime_identity_is_current() -> None:
    assert NATIVE_RUNTIME_SCHEMA_VERSION == 2
    assert NATIVE_RUNTIME_KIND == "go-native"
    assert DEFAULT_NATIVE_RUNTIME_BUILD_ROOT.as_posix() == "out/native-runtime"



def _load_final_native_runtime_release_check_module():
    import importlib.util

    script = Path("scripts/final-native-runtime-release-check.py")
    spec = importlib.util.spec_from_file_location("final_native_runtime_release_check", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_final_native_runtime_release_check_requires_runtime_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_final_native_runtime_release_check_module()

    class Result:
        ok = True
        checked = ()
        mismatches = ()

        def require_ok(self) -> None:
            return None

    monkeypatch.setattr(module, "check_release_parity", lambda repo: Result())
    monkeypatch.setattr(module, "validate_native_runtime_artifact", lambda path: (_ for _ in ()).throw(FileNotFoundError(path)))
    monkeypatch.setattr("sys.argv", ["final-native-runtime-release-check.py", "--repo-root", str(tmp_path)])

    with pytest.raises(FileNotFoundError):
        module.main()


def test_final_native_runtime_release_check_has_explicit_source_only_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_final_native_runtime_release_check_module()

    class Result:
        ok = True
        checked = ()
        mismatches = ()

        def require_ok(self) -> None:
            return None

    monkeypatch.setattr(module, "check_release_parity", lambda repo: Result())
    monkeypatch.setattr(module, "validate_native_runtime_artifact", lambda path: (_ for _ in ()).throw(AssertionError("should not validate runtime")))
    monkeypatch.setattr("sys.argv", ["final-native-runtime-release-check.py", "--repo-root", str(tmp_path), "--skip-runtime-integrity"])

    assert module.main() == 0
    assert "native-runtime-integrity" not in capsys.readouterr().out
