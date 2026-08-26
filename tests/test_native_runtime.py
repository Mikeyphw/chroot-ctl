from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrootctl.native_runtime import (
    DEFAULT_NATIVE_RUNTIME_BUILD_ROOT,
    DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
    assert_native_termux_build_host,
    detect_android_abi,
    is_native_termux_environment,
    nuitka_command,
    validate_native_runtime_artifact,
    write_native_runtime_manifest,
)


def _fake_runtime(root: Path) -> Path:
    artifact = root / "arm64-v8a"
    entrypoint = artifact / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_bytes(b"\x7fELF" + b"fake-native-runtime")
    entrypoint.chmod(0o755)
    library = entrypoint.parent / "libpython-test.so"
    library.write_bytes(b"fake-library")
    library.chmod(0o644)
    write_native_runtime_manifest(
        artifact,
        abi="arm64-v8a",
        package_version="0.11.0",
        bridge_protocol_version=1,
        nuitka_version="test",
    )
    return artifact


def test_android_abi_and_termux_host_detection_are_fail_closed() -> None:
    env = {"PREFIX": "/data/data/com.termux/files/usr"}
    assert detect_android_abi(machine="aarch64") == "arm64-v8a"
    assert is_native_termux_environment(environ=env, machine="aarch64") is True
    assert assert_native_termux_build_host(environ=env, machine="arm64") == "arm64-v8a"
    assert is_native_termux_environment(environ={"PREFIX": "/usr"}, machine="aarch64") is False
    with pytest.raises(RuntimeError, match="native Termux"):
        assert_native_termux_build_host(environ={"PREFIX": "/usr"}, machine="aarch64")
    with pytest.raises(RuntimeError, match="unsupported Android host architecture"):
        detect_android_abi(machine="x86_64")


def test_nuitka_command_is_standalone_android_runtime_shape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "chrootctl-native-entry.py").write_text("pass\n", encoding="utf-8")
    command = nuitka_command(repo_root=repo, output_dir=tmp_path / "out", jobs=2, python_executable="python3")
    joined = " ".join(command)
    assert command[:3] == ("python3", "-m", "nuitka")
    assert "--mode=standalone" in command
    assert "--clang" in command
    assert "--include-package=chrootctl" in command
    assert "--include-package-data=chrootctl" in command
    assert "--jobs=2" in command
    assert "--onefile" not in joined
    assert DEFAULT_NATIVE_RUNTIME_BUILD_ROOT.as_posix() == "out/native-runtime"


def test_native_runtime_manifest_seals_every_file(tmp_path: Path) -> None:
    artifact = _fake_runtime(tmp_path)
    manifest = validate_native_runtime_artifact(
        artifact,
        expected_abi="arm64-v8a",
        package_version="0.11.0",
        bridge_protocol_version=1,
    )
    assert manifest["runtimeKind"] == "nuitka-standalone"
    assert manifest["platform"] == "android"
    assert manifest["entrypoint"] == DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    assert len(manifest["files"]) == 2

    library = artifact / "chrootctl.dist/libpython-test.so"
    library.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity mismatch"):
        validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)


def test_native_runtime_manifest_rejects_uninventoried_file_and_wrong_release(tmp_path: Path) -> None:
    artifact = _fake_runtime(tmp_path)
    (artifact / "chrootctl.dist/extra.so").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="inventory mismatch"):
        validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)

    artifact = _fake_runtime(tmp_path / "second")
    payload = json.loads((artifact / "runtime-manifest.json").read_text(encoding="utf-8"))
    payload["pythonPackageVersion"] = "0.10.0"
    (artifact / "runtime-manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="package version"):
        validate_native_runtime_artifact(artifact, package_version="0.11.0", bridge_protocol_version=1)


def test_native_runtime_validator_rejects_symlink_artifact_root(tmp_path: Path) -> None:
    artifact = _fake_runtime(tmp_path / "real")
    link = tmp_path / "link"
    link.symlink_to(artifact, target_is_directory=True)
    with pytest.raises(NotADirectoryError, match="real directory"):
        validate_native_runtime_artifact(link, package_version="0.11.0", bridge_protocol_version=1)
