from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrootctl.native_runtime import (
    DEFAULT_NATIVE_ONEFILE_EXPERIMENT_NAME,
    DEFAULT_NATIVE_ONEFILE_EXPERIMENT_ROOT,
    DEFAULT_NATIVE_RUNTIME_BUILD_ROOT,
    native_onefile_experiment_plan,
    nuitka_onefile_experiment_command,
)
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


def test_onefile_experiment_command_is_explicitly_separate_from_supported_standalone(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "chrootctl-native-entry.py").write_text("pass\n", encoding="utf-8")

    command = nuitka_onefile_experiment_command(repo_root=repo, output_dir=tmp_path / "onefile", jobs=1, python_executable="python3")
    joined = " ".join(command)
    assert command[:3] == ("python3", "-m", "nuitka")
    assert "--mode=onefile" in command
    assert "--mode=standalone" not in command
    assert f"--output-filename={DEFAULT_NATIVE_ONEFILE_EXPERIMENT_NAME}" in command
    assert DEFAULT_NATIVE_RUNTIME_BUILD_ROOT.as_posix() == "out/native-runtime"
    assert DEFAULT_NATIVE_ONEFILE_EXPERIMENT_ROOT.as_posix() == "out/native-runtime-onefile"
    assert "chrootctl.dist" not in joined


def test_onefile_experiment_plan_rejects_symlink_output_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "chrootctl-native-entry.py").write_text("pass\n", encoding="utf-8")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="onefile experiment output root"):
        native_onefile_experiment_plan(repo, output_root=link)
