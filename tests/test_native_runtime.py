from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrootctl.native_runtime import (
    DEFAULT_NATIVE_RUNTIME_BUILD_ROOT,
    DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
    LEGACY_NATIVE_RUNTIME_KIND,
    LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION,
    NATIVE_RUNTIME_KIND,
    NATIVE_RUNTIME_SCHEMA_VERSION,
    detect_android_abi,
    go_android_build_command,
    validate_native_runtime_artifact,
    write_native_runtime_manifest,
)


def _fake_runtime(root: Path, *, legacy: bool = False) -> Path:
    artifact = root / "arm64-v8a"
    entrypoint = artifact / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_bytes(b"\x7fELF" + b"fake-go-native-runtime")
    entrypoint.chmod(0o755)
    write_native_runtime_manifest(
        artifact,
        abi="arm64-v8a",
        package_version="0.11.0",
        bridge_protocol_version=1,
        compiler_version="go-test",
        schema_version=LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION if legacy else NATIVE_RUNTIME_SCHEMA_VERSION,
        runtime_kind=LEGACY_NATIVE_RUNTIME_KIND if legacy else NATIVE_RUNTIME_KIND,
    )
    return artifact


def test_android_abi_is_fail_closed() -> None:
    assert detect_android_abi(machine="aarch64") == "arm64-v8a"
    assert detect_android_abi(machine="arm64") == "arm64-v8a"
    with pytest.raises(RuntimeError, match="unsupported Android host architecture"):
        detect_android_abi(machine="x86_64")


def test_go_android_build_command_targets_complete_cli(tmp_path: Path) -> None:
    repo = tmp_path / "repo"; (repo / "cmd/chrootctl").mkdir(parents=True); (repo / "go.mod").write_text("module chrootctl\n")
    command = go_android_build_command(repo_root=repo, output_binary=tmp_path / "out/chrootctl", go_executable="go")
    assert command[:4] == ("go", "build", "-trimpath", "-tags")
    assert "android" in command
    assert command[-1] == "./cmd/chrootctl"
    assert DEFAULT_NATIVE_RUNTIME_BUILD_ROOT.as_posix() == "out/native-runtime"


def test_go_native_runtime_manifest_seals_single_elf(tmp_path: Path) -> None:
    artifact = _fake_runtime(tmp_path)
    manifest = validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)
    assert manifest["schemaVersion"] == 2
    assert manifest["runtimeKind"] == "go-native"
    assert manifest["backendVersion"] == "0.11.0"
    assert manifest["compiler"]["name"] == "Go"
    assert [row["path"] for row in manifest["files"]] == ["chrootctl"]
    (artifact / "chrootctl").write_bytes(b"tampered")
    with pytest.raises((ValueError, PermissionError), match="integrity|ELF"):
        validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)


def test_validator_retains_legacy_schema1_read_compatibility(tmp_path: Path) -> None:
    artifact = _fake_runtime(tmp_path, legacy=True)
    manifest = validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)
    assert manifest["schemaVersion"] == 1
    assert manifest["runtimeKind"] == "nuitka-onefile"
    assert manifest["pythonPackageVersion"] == "0.11.0"


def test_runtime_manifest_rejects_uninventoried_file_and_wrong_release(tmp_path: Path) -> None:
    artifact = _fake_runtime(tmp_path)
    (artifact / "extra.so").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="inventory mismatch"):
        validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)
    artifact = _fake_runtime(tmp_path / "second")
    payload = json.loads((artifact / "runtime-manifest.json").read_text())
    payload["backendVersion"] = "0.10.0"
    (artifact / "runtime-manifest.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="package version"):
        validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)


def test_native_runtime_validator_rejects_symlink_artifact_root(tmp_path: Path) -> None:
    artifact = _fake_runtime(tmp_path / "real")
    link = tmp_path / "link"; link.symlink_to(artifact, target_is_directory=True)
    with pytest.raises(NotADirectoryError, match="real directory"):
        validate_native_runtime_artifact(link, package_version="0.11.0", bridge_protocol_version=1)
