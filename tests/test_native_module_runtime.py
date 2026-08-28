from __future__ import annotations

import json
from pathlib import Path

from chrootctl.magisk import (
    ANDROID_APP_VERSION_CODE,
    ANDROID_APP_VERSION_NAME,
    BRIDGE_PROTOCOL_VERSION,
    DEFAULT_MODULE_ID,
    DEFAULT_MODULE_VERSION,
    DEFAULT_MODULE_VERSION_CODE,
    PYTHON_PACKAGE_VERSION,
)
from chrootctl.native_runtime import DEFAULT_NATIVE_RUNTIME_ABI, write_native_runtime_manifest
from chrootctl.services.module_runtime import ModuleRuntimePaths, ModuleRuntimeStatusService


def _module(active_root: Path) -> Path:
    root = active_root / DEFAULT_MODULE_ID
    (root / "system/bin").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "config/chrootctl").mkdir(parents=True)
    runtime = root / "runtime" / DEFAULT_NATIVE_RUNTIME_ABI
    runtime.mkdir(parents=True)

    (root / "module.prop").write_text(
        f"id={DEFAULT_MODULE_ID}\nname=chrootctl Magisk Module\nversion={DEFAULT_MODULE_VERSION}\nversionCode={DEFAULT_MODULE_VERSION_CODE}\n",
        encoding="utf-8",
    )
    for relative in ("system/bin/chrootctl", "bin/chrootctl-magisk-helper"):
        path = root / relative
        path.write_text("#!/system/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    compatibility = {
        "schemaVersion": 2,
        "project": "chrootctl",
        "bridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        "pythonPackage": {"name": "chrootctl", "version": PYTHON_PACKAGE_VERSION},
        "androidApp": {
            "applicationId": "com.mikeyphw.chrootctl",
            "versionName": ANDROID_APP_VERSION_NAME,
            "versionCode": ANDROID_APP_VERSION_CODE,
            "minimumSupportedModuleVersionCode": DEFAULT_MODULE_VERSION_CODE,
        },
        "module": {
            "id": DEFAULT_MODULE_ID,
            "version": DEFAULT_MODULE_VERSION,
            "versionCode": DEFAULT_MODULE_VERSION_CODE,
            "minimumSupportedBridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        },
    }
    (root / "config/chrootctl/compatibility-manifest.json").write_text(
        json.dumps(compatibility), encoding="utf-8"
    )
    entry = runtime / "chrootctl"
    entry.write_bytes(b"\x7fELF-native-test")
    entry.chmod(0o755)
    (runtime / "library.so").write_bytes(b"library")
    write_native_runtime_manifest(
        runtime,
        abi=DEFAULT_NATIVE_RUNTIME_ABI,
        package_version=PYTHON_PACKAGE_VERSION,
        bridge_protocol_version=BRIDGE_PROTOCOL_VERSION,
        nuitka_version="test",
    )
    return root


def _service(active_root: Path) -> ModuleRuntimeStatusService:
    return ModuleRuntimeStatusService(ModuleRuntimePaths(active_root=active_root, pending_roots=()))


def test_module_runtime_ready_uses_sealed_native_bundle(tmp_path: Path) -> None:
    active_root = tmp_path / "modules"
    active_root.mkdir()
    root = _module(active_root)
    status = _service(active_root).status()
    assert status["ready"] is True
    assert status["active"]["runtimeReadiness"]["mode"] == "bundled-native"
    assert status["active"]["dependencyReadiness"] == status["active"]["runtimeReadiness"]
    assert status["active"]["runtimeReadiness"]["executable"].endswith("runtime/arm64-v8a/chrootctl")
    assert _service(active_root).active_executable() == root / "system/bin/chrootctl"


def test_module_runtime_tamper_fails_readiness_and_execution(tmp_path: Path) -> None:
    active_root = tmp_path / "modules"
    active_root.mkdir()
    root = _module(active_root)
    (root / "runtime/arm64-v8a/library.so").write_bytes(b"tampered")
    service = _service(active_root)
    status = service.status()
    assert status["active"] is not None
    assert status["ready"] is False
    assert status["active"]["runtimeReadiness"]["reason"] == "native_runtime_integrity_invalid"
    assert service.active_executable() is None


def test_module_runtime_never_requires_external_python_readiness(tmp_path: Path) -> None:
    active_root = tmp_path / "modules"
    active_root.mkdir()
    root = _module(active_root)
    assert not (root / "config/chrootctl/dependencies.ready.json").exists()
    assert not (root / "payload/requirements.txt").exists()
    assert _service(active_root).status()["ready"] is True


def test_module_runtime_missing_native_manifest_is_not_active(tmp_path: Path) -> None:
    active_root = tmp_path / "modules"
    active_root.mkdir()
    root = _module(active_root)
    (root / "runtime/arm64-v8a/runtime-manifest.json").unlink()
    status = _service(active_root).status()
    assert status["ready"] is False
    assert status["active"] is None
    assert status["installedState"]["layoutReady"] is False


def test_module_launcher_uses_non_colliding_native_entrypoint(tmp_path: Path) -> None:
    from chrootctl.magisk import MagiskModuleConfig, render_magisk_module

    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True)
    entry = runtime / "chrootctl"
    entry.write_bytes(b"\x7fELFfake")
    entry.chmod(0o755)

    from chrootctl.native_runtime import write_native_runtime_manifest
    from chrootctl.magisk import PYTHON_PACKAGE_VERSION, BRIDGE_PROTOCOL_VERSION

    write_native_runtime_manifest(
        runtime,
        abi="arm64-v8a",
        package_version=PYTHON_PACKAGE_VERSION,
        bridge_protocol_version=BRIDGE_PROTOCOL_VERSION,
        nuitka_version="test",
    )

    output = tmp_path / "module"
    render_magisk_module(output, services=None, startup_targets=(), module_config=MagiskModuleConfig(native_runtime_dir=runtime))

    launcher = (output / "system/bin/chrootctl").read_text()
    assert 'RUNTIME_BIN="$RUNTIME_ROOT/chrootctl"' in launcher
    assert 'RUNTIME_BIN="$RUNTIME_ROOT/chrootctl"' in launcher


def test_onefile_module_launcher_uses_root_runtime_binary(tmp_path: Path) -> None:
    from chrootctl.magisk import MagiskModuleConfig, render_magisk_module
    from chrootctl.native_runtime import write_native_runtime_manifest
    from chrootctl.magisk import PYTHON_PACKAGE_VERSION, BRIDGE_PROTOCOL_VERSION

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    entry = runtime / "chrootctl"
    entry.write_bytes(b"\x7fELFfake")
    entry.chmod(0o755)

    write_native_runtime_manifest(
        runtime,
        abi="arm64-v8a",
        package_version=PYTHON_PACKAGE_VERSION,
        bridge_protocol_version=BRIDGE_PROTOCOL_VERSION,
        nuitka_version="test",
    )

    output = tmp_path / "module"
    render_magisk_module(
        output,
        services=None,
        startup_targets=(),
        module_config=MagiskModuleConfig(native_runtime_dir=runtime),
    )

    launcher = (output / "system/bin/chrootctl").read_text()
    assert 'RUNTIME_BIN="$RUNTIME_ROOT/chrootctl"' in launcher
    assert "chrootctl.dist" not in launcher
