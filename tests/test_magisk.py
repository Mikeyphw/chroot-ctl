from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from chrootctl.native_runtime import DEFAULT_NATIVE_RUNTIME_ENTRYPOINT, write_native_runtime_manifest

from chrootctl.magisk import (
    MagiskModuleConfig,
    render_magisk_module,
    resolve_startup_targets,
    validate_magisk_module,
    validate_magisk_zip,
    zip_magisk_module,
)


class _FakeChroot:
    def __init__(self, name: str, installed: bool) -> None:
        self.name = name
        self.installed = installed


class _FakeChrootsService:
    def list(self):
        return [_FakeChroot("work", True), _FakeChroot("dev", True), _FakeChroot("stale", False)]


class _FakeServices:
    def chroots(self):
        return _FakeChrootsService()


def _build_package_source(tmp_path: Path) -> Path:
    package_root = tmp_path / "pkgroot" / "src"
    chrootctl_dir = package_root / "chrootctl"
    chrootctl_dir.mkdir(parents=True)
    (chrootctl_dir / "__init__.py").write_text("", encoding="utf-8")
    (chrootctl_dir / "cli.py").write_text("def main():\n    return None\n", encoding="utf-8")
    repo_root = package_root.parent
    (repo_root / "pyproject.toml").write_text('[project]\nname="chrootctl"\nversion="0.11.0"\n', encoding="utf-8")
    android = repo_root / "android/app"
    android.mkdir(parents=True)
    (android / "build.gradle.kts").write_text('android { defaultConfig { versionCode = 1; versionName = "0.1.0-phase29" } }\n', encoding="utf-8")
    release = repo_root / "docs/release"
    release.mkdir(parents=True)
    (release / "compatibility-manifest.json").write_text(json.dumps({
        "schemaVersion": 2,
        "project": "chrootctl",
        "bridgeProtocolVersion": 1,
        "pythonPackage": {"name": "chrootctl", "version": "0.11.0"},
        "androidApp": {
            "applicationId": "com.mikeyphw.chrootctl",
            "versionName": "0.1.0-phase29",
            "versionCode": 1,
            "minimumSupportedModuleVersionCode": 15,
        },
        "module": {
            "id": "chrootctl-magisk",
            "version": "1.3.0",
            "versionCode": 15,
            "minimumSupportedBridgeProtocolVersion": 1,
        },
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runtime = repo_root / "out/native-runtime/arm64-v8a"
    entrypoint = runtime / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_bytes(b"\x7fELFfake-chrootctl")
    entrypoint.chmod(0o755)
    (entrypoint.parent / "libfake.so").write_bytes(b"fake-library")
    write_native_runtime_manifest(
        runtime,
        abi="arm64-v8a",
        package_version="0.11.0",
        bridge_protocol_version=1,
        nuitka_version="test",
    )
    return package_root


def test_resolve_startup_targets_requires_installed_selected_names() -> None:
    services = _FakeServices()
    assert resolve_startup_targets(services) == ()
    assert resolve_startup_targets(services, all_installed=True) == ("dev", "work")
    assert resolve_startup_targets(services, selected_names=("dev", "work", "dev")) == ("dev", "work")
    with pytest.raises(ValueError, match="installed chroots"):
        resolve_startup_targets(services, selected_names=("stale",))


def test_render_magisk_module_writes_active_only_safe_runtime(tmp_path: Path) -> None:
    output_dir = tmp_path / "magisk-module"
    result = render_magisk_module(
        output_dir,
        services=_FakeServices(),
        startup_targets=("work", "dev"),
        module_config=MagiskModuleConfig(package_source_dir=_build_package_source(tmp_path)),
    )
    assert result.output_dir == output_dir
    required = validate_magisk_module(output_dir)
    assert required
    compat = json.loads((output_dir / "config/chrootctl/compatibility-manifest.json").read_text(encoding="utf-8"))
    assert compat["schemaVersion"] == 2
    assert compat["module"]["id"] == "chrootctl-magisk"
    assert compat["module"]["versionCode"] == 15

    customize = (output_dir / "customize.sh").read_text(encoding="utf-8")
    service = (output_dir / "service.sh").read_text(encoding="utf-8")
    helper = (output_dir / "bin/chrootctl-magisk-helper").read_text(encoding="utf-8")
    launcher = (output_dir / "system/bin/chrootctl").read_text(encoding="utf-8")
    assert '. "$MODPATH/config/chrootctl/python.env"' not in customize
    assert '. "$MODDIR/config/chrootctl/python.env"' not in service
    assert not (output_dir / "bin/chrootctl-python-bootstrap").exists()
    assert not (output_dir / "system/bin/chrootctl-python-bootstrap").exists()
    assert not (output_dir / "payload").exists()
    assert not (output_dir / "config/chrootctl/dependency-mode.env").exists()
    assert "dependencies.ready.json" not in launcher
    assert '' in launcher
    assert 'RUNTIME_BIN="$RUNTIME_ROOT/chrootctl"' in launcher
    assert "LD_LIBRARY_PATH" not in launcher
    assert "onefile-runtime" not in launcher
    assert "/data/adb/modules/chrootctl-magisk" in launcher
    assert "/data/adb/modules_update/chrootctl-magisk" in launcher  # diagnostics only
    assert 'run --boot' not in service
    assert 'clipboard.enabled' in service
    assert 'bootstrap.lock' not in customize + service + helper + launcher
    assert 'mount|unmount|start|restart' not in helper
    assert '"$CLI" --name "$name" mount' not in helper
    assert "__module-boot" in helper
    assert "PYTHON_BIN" not in helper
    assert "OperationManager" not in helper
    assert "refusing module service outside active module" in service
    assert "no external Python environment" in customize
    assert "command -v python3" not in customize
    assert "pip install" not in customize
    for script in (customize, service, helper, launcher):
        assert "chrootctl-python-bootstrap" not in script
        assert "python.env" not in script
        assert "dependency-mode.env" not in script
        assert "dependencies.ready.json" not in script
        assert "PYTHON_BIN" not in script
        assert "PYTHONPATH" not in script


def test_module_validator_rejects_backup_and_symlink_payloads(tmp_path: Path) -> None:
    output_dir = tmp_path / "module"
    render_magisk_module(
        output_dir,
        services=_FakeServices(),
        startup_targets=(),
        module_config=MagiskModuleConfig(package_source_dir=_build_package_source(tmp_path)),
    )
    runtime_dist = output_dir / "runtime/arm64-v8a"
    bad = runtime_dist / "secret.so.bak"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden"):
        validate_magisk_module(output_dir)
    bad.unlink()
    link = runtime_dist / "link.so"
    link.symlink_to(runtime_dist / "libfake.so")
    with pytest.raises(ValueError, match="symlink"):
        validate_magisk_module(output_dir)


def test_zip_magisk_module_deep_validates_final_zip(tmp_path: Path) -> None:
    output_dir = tmp_path / "module"
    zip_path = tmp_path / "chrootctl-magisk.zip"
    render_magisk_module(
        output_dir,
        services=_FakeServices(),
        startup_targets=("work",),
        module_config=MagiskModuleConfig(package_source_dir=_build_package_source(tmp_path)),
    )
    zip_magisk_module(output_dir, zip_path)
    names = set(validate_magisk_zip(zip_path))
    assert "module.prop" in names
    assert "config/chrootctl/compatibility-manifest.json" in names
    assert "system/bin/chrootctl" in names
    assert "runtime/arm64-v8a/runtime-manifest.json" in names
    assert "runtime/arm64-v8a/chrootctl" in names
    assert "bin/chrootctl-python-bootstrap" not in names
    assert "system/bin/chrootctl-python-bootstrap" not in names
    assert not any(name.startswith("payload/") for name in names)
    assert not any(name.endswith((".bak", ".orig", ".rej")) for name in names)
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo("system/bin/chrootctl")
        mode = (info.external_attr >> 16) & 0o777
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
    assert mode & 0o111


def test_magisk_render_parser_collects_targets(tmp_path: Path) -> None:
    from chrootctl.parser import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "magisk", "render", "--output", str(tmp_path / "module"), "--zip", str(tmp_path / "module.zip"),
        "--all-installed", "--name", "work", "--name", "dev",
    ])
    assert args.command == "magisk"
    assert args.magisk_command == "render"
    assert args.all_installed is True
    assert args.magisk_names == ["work", "dev"]
    with pytest.raises(SystemExit):
        parser.parse_args(["magisk", "render", "--output", str(tmp_path / "module2"), "--wheelhouse", str(tmp_path / "wheelhouse")])


def test_render_magisk_module_rejects_symlinked_native_runtime_root(tmp_path: Path) -> None:
    package_root = _build_package_source(tmp_path)
    runtime = package_root.parent / "out/native-runtime/arm64-v8a"
    link = tmp_path / "native-runtime-link"
    link.symlink_to(runtime, target_is_directory=True)
    with pytest.raises(NotADirectoryError, match="real directory"):
        render_magisk_module(
            tmp_path / "module-from-link",
            services=_FakeServices(),
            startup_targets=(),
            module_config=MagiskModuleConfig(package_source_dir=package_root, native_runtime_dir=link),
        )


def test_customize_sh_is_kernelsu_source_safe() -> None:
    from chrootctl.magisk import _customize_sh

    script = _customize_sh()
    assert "set -u" not in script
    assert "set -eu" not in script
    assert 'REPLACE=""' in script
    assert "SKIPMOUNT=false" in script
    assert "PROPFILE=false" in script
    assert "POSTFSDATA=true" in script
    assert "LATESTARTSERVICE=true" in script
    assert "return 0 2>/dev/null || exit 0" in script
