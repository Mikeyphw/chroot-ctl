from __future__ import annotations

import json
from pathlib import Path

from chrootctl.magisk import MagiskModuleConfig, render_magisk_module, resolve_startup_targets, zip_magisk_module


class _FakeChroot:
    def __init__(self, name: str, installed: bool) -> None:
        self.name = name
        self.installed = installed


class _FakeChrootsService:
    def list(self):
        return [
            _FakeChroot("work", True),
            _FakeChroot("dev", True),
            _FakeChroot("stale", False),
        ]


class _FakeServices:
    def chroots(self):
        return _FakeChrootsService()


def _build_package_source(tmp_path: Path) -> Path:
    package_root = tmp_path / "pkgroot" / "src"
    chrootctl_dir = package_root / "chrootctl"
    chrootctl_dir.mkdir(parents=True)
    (chrootctl_dir / "__init__.py").write_text("", encoding="utf-8")
    (chrootctl_dir / "cli.py").write_text("def main():\n    return None\n", encoding="utf-8")
    web_dir = chrootctl_dir / "web"
    web_dir.mkdir()
    (web_dir / "__init__.py").write_text("", encoding="utf-8")
    (web_dir / "app.py").write_text("def main():\n    return None\n", encoding="utf-8")
    routes_dir = web_dir / "routes"
    routes_dir.mkdir()
    (routes_dir / "__init__.py").write_text("", encoding="utf-8")
    (routes_dir / "ksu.py").write_text("router = None\n", encoding="utf-8")
    templates_dir = web_dir / "templates"
    templates_dir.mkdir()
    (templates_dir / "ksu.html").write_text("<h1>KSU</h1>\n", encoding="utf-8")
    (package_root.parent / "pyproject.toml").write_text(
        "\n".join(
            (
                "[build-system]",
                'requires = ["setuptools>=68"]',
                'build-backend = "setuptools.build_meta"',
                "",
                "[project]",
                'name = "chrootctl"',
                'version = "0.0.0"',
                "",
                "[tool.setuptools]",
                'package-dir = {"" = "src"}',
                "",
            )
        ),
        encoding="utf-8",
    )
    return package_root


def test_resolve_startup_targets_prefers_selected_names() -> None:
    services = _FakeServices()

    assert resolve_startup_targets(services, selected_names=("dev", "work", "dev")) == ("dev", "work")


def test_resolve_startup_targets_can_include_all_installed() -> None:
    services = _FakeServices()

    assert resolve_startup_targets(services, all_installed=True) == ("work", "dev")


def test_render_magisk_module_writes_full_module_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "magisk-module"
    package_source_dir = _build_package_source(tmp_path)

    result = render_magisk_module(
        output_dir,
        services=_FakeServices(),
        startup_targets=("work", "dev"),
        module_config=MagiskModuleConfig(package_source_dir=package_source_dir),
    )

    assert result.output_dir == output_dir
    assert (output_dir / "service.sh").exists()
    assert (output_dir / "post-fs-data.sh").exists()
    assert (output_dir / "customize.sh").exists()
    assert (output_dir / "system" / "bin" / "chrootctl").exists()
    assert (output_dir / "system" / "bin" / "chrootctl-web").exists()
    assert (output_dir / "system" / "bin" / "chrootctl-magisk-helper").exists()
    assert (output_dir / "system" / "bin" / "chrootctl-python-bootstrap").exists()
    assert (output_dir / "system" / "bin" / "chrootctl-webui-service").exists()
    assert (output_dir / "bin" / "chrootctl-magisk-helper").exists()
    assert (output_dir / "bin" / "chrootctl-python-bootstrap").exists()
    assert (output_dir / "bin" / "chrootctl-webui-service").exists()
    assert (output_dir / "payload" / "requirements.txt").exists()
    assert (output_dir / "payload" / "src" / "chrootctl" / "cli.py").exists()
    assert (output_dir / "webroot" / "index.html").exists()
    assert (output_dir / "webroot" / "icon.svg").exists()
    assert (output_dir / "config" / "chrootctl" / "boot_targets.json").exists()
    assert (output_dir / "config" / "chrootctl" / "dependency-mode.env").exists()
    assert (output_dir / "wheelhouse" / ".keep").exists()

    customize_text = (output_dir / "customize.sh").read_text(encoding="utf-8")
    service_text = (output_dir / "service.sh").read_text(encoding="utf-8")
    helper_text = (output_dir / "bin" / "chrootctl-magisk-helper").read_text(encoding="utf-8")
    payload = json.loads((output_dir / "config" / "chrootctl" / "boot_targets.json").read_text(encoding="utf-8"))
    launcher_text = (output_dir / "system" / "bin" / "chrootctl").read_text(encoding="utf-8")
    service_proxy_text = (output_dir / "system" / "bin" / "chrootctl-webui-service").read_text(encoding="utf-8")
    supervisor_text = (output_dir / "bin" / "chrootctl-webui-service").read_text(encoding="utf-8")
    module_prop_text = (output_dir / "module.prop").read_text(encoding="utf-8")
    ksu_webroot_text = (output_dir / "webroot" / "index.html").read_text(encoding="utf-8")

    assert "metamodule=1" not in module_prop_text
    assert "webuiIcon=webroot/icon.svg" in module_prop_text
    assert 'const SERVICE = MODDIR + "/system/bin/chrootctl-webui-service";' in ksu_webroot_text
    assert 'Open in browser' in ksu_webroot_text
    assert payload["startup_targets"] == ["work", "dev"]
    bootstrap_text = (output_dir / "bin" / "chrootctl-python-bootstrap").read_text(encoding="utf-8")

    assert 'PYTHON_PATH_BIN="$(command -v python3 2>/dev/null || true)"' in customize_text
    assert 'ui_print "- Python runtime used by module: $PYTHON_BIN"' in customize_text
    assert 'No Python dependencies are installed during Magisk/KSU install' in customize_text
    assert "pip install" not in customize_text
    assert "pydantic_core" in customize_text
    dependency_mode_text = (output_dir / "config" / "chrootctl" / "dependency-mode.env").read_text(encoding="utf-8")
    assert 'static-python-env' in dependency_mode_text
    assert 'DEPENDENCY_INSTALL_PHASE="none"' in dependency_mode_text
    assert 'DEPENDENCY_REPAIR="disabled"' in dependency_mode_text
    assert 'pip install' not in bootstrap_text
    assert '--extra-index-url' not in bootstrap_text
    assert '--only-binary' not in bootstrap_text
    assert 'validate_static_environment' in bootstrap_text
    assert 'Fix the static Python module environment' in bootstrap_text
    assert 'TypeAdapter' in bootstrap_text
    assert '[ -x "$WEBUI_SERVICE" ] && "$WEBUI_SERVICE" start "$MODDIR"' in service_text
    assert '"$CLI" --name "$name" mount' in helper_text
    assert 'MODDIR="$(resolve_moddir)"' in launcher_text
    assert 'PAYLOAD_SRC="$MODDIR/payload/src"' in launcher_text
    assert 'exec "$PYTHON_BIN" -m chrootctl.cli "$@"' in launcher_text
    assert 'MODDIR="$(resolve_moddir)"' in service_proxy_text
    assert 'TARGET="$MODDIR/bin/chrootctl-webui-service"' in service_proxy_text
    assert 'runtime_ready' in supervisor_text
    assert '"$BOOTSTRAP" "$MODDIR"' in supervisor_text
    assert '"$WEBUI" --host "$HOST" --port "$PORT"' in supervisor_text



def test_zip_magisk_module_writes_flashable_root_entries(tmp_path: Path) -> None:
    output_dir = tmp_path / "magisk-module"
    package_source_dir = _build_package_source(tmp_path)
    zip_path = tmp_path / "chrootctl-magisk.zip"

    render_magisk_module(
        output_dir,
        services=_FakeServices(),
        startup_targets=("work",),
        module_config=MagiskModuleConfig(package_source_dir=package_source_dir),
    )
    zip_magisk_module(output_dir, zip_path)

    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "module.prop" in names
    assert "service.sh" in names
    assert "webroot/index.html" in names
    assert "webroot/icon.svg" in names
    assert "bin/chrootctl-python-bootstrap" in names
    assert "system/bin/chrootctl" in names
    assert "system/bin/chrootctl-magisk-helper" in names
    assert "system/bin/chrootctl-python-bootstrap" in names
    assert "system/bin/chrootctl-webui-service" in names
    assert "payload/src/chrootctl/web/routes/ksu.py" in names
    assert not any(name.startswith("magisk-module/") for name in names)


def test_magisk_render_parser_collects_targets(tmp_path: Path) -> None:
    from chrootctl.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "magisk",
            "render",
            "--output",
            str(tmp_path / "module"),
            "--zip",
            str(tmp_path / "module.zip"),
            "--wheelhouse",
            str(tmp_path / "wheelhouse"),
            "--all-installed",
            "--name",
            "work",
            "--name",
            "dev",
        ]
    )

    assert args.command == "magisk"
    assert args.magisk_command == "render"
    assert args.all_installed is True
    assert args.zip_path == tmp_path / "module.zip"
    assert args.wheelhouse_dir == tmp_path / "wheelhouse"
    assert args.magisk_names == ["work", "dev"]
