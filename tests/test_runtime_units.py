from __future__ import annotations

from pathlib import Path

import pytest

from chrootctl.config import ChrootConfig
from chrootctl.runtime.units import ServiceCatalog, load_service_unit


def test_load_service_unit_parses_systemd_inspired_file(tmp_path: Path) -> None:
    unit_path = tmp_path / "serve-web.service"
    unit_path.write_text(
        """
[Unit]
Description=Code web server

[Service]
Chroot=code
User=mike
WorkingDirectory=/home/mike/project
Environment=PORT=8080 NODE_ENV=production
ExecStart=code serve-web --host 0.0.0.0 --port 8080
X11=false

[Install]
WantedBy=boot.target
Enabled=true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    unit = load_service_unit(unit_path)

    assert unit.name == "serve-web"
    assert unit.description == "Code web server"
    assert unit.chroot == "code"
    assert unit.user == "mike"
    assert unit.environment == {"PORT": "8080", "NODE_ENV": "production"}
    assert unit.wanted_by == ("boot.target",)
    assert unit.enabled is True
    assert "cd /home/mike/project" in unit.command_text()
    assert "export PORT=8080" in unit.command_text()
    assert "exec code serve-web" in unit.command_text()


def test_service_catalog_reads_configured_service_dirs(tmp_path: Path) -> None:
    service_dir = tmp_path / "services"
    service_dir.mkdir()
    (service_dir / "serve-web.service").write_text(
        """
[Service]
Chroot=code
ExecStart=python3 -m http.server 8080

[Install]
WantedBy=boot.target
""".strip()
        + "\n",
        encoding="utf-8",
    )
    cfg = ChrootConfig(service_dirs=(service_dir,), service_state_dir=tmp_path / "run", service_log_dir=tmp_path / "logs")

    catalog = ServiceCatalog(cfg)

    assert [unit.name for unit in catalog.list_units()] == ["serve-web"]
    assert catalog.get("serve-web").chroot == "code"


def test_load_service_unit_requires_exec_start(tmp_path: Path) -> None:
    unit_path = tmp_path / "broken.service"
    unit_path.write_text("[Service]\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="ExecStart is required"):
        load_service_unit(unit_path)


def _write_unit(path: Path, *, name: str, chroot: str = "code", body: str = "", enabled: bool = True) -> Path:
    unit_path = path / f"{name}.service"
    unit_path.write_text(
        f"""
[Unit]
Description={name}
{body}

[Service]
Chroot={chroot}
ExecStart=/bin/true

[Install]
WantedBy=boot.target
Enabled={'true' if enabled else 'false'}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return unit_path


def test_service_unit_requires_bound_chroot(tmp_path: Path) -> None:
    unit_path = tmp_path / "broken.service"
    unit_path.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Chroot is required"):
        load_service_unit(unit_path)


def test_service_runner_enable_disable_markers(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from chrootctl.runtime.units import ServiceRunner

    service_dir = tmp_path / "services"
    service_dir.mkdir()
    _write_unit(service_dir, name="serve-web", enabled=False)
    cfg = ChrootConfig(service_dirs=(service_dir,), service_state_dir=tmp_path / "run", service_log_dir=tmp_path / "logs")
    context = SimpleNamespace(config=cfg, runner=SimpleNamespace(dry_run=False), logger=None)
    runner = ServiceRunner(context)

    unit = runner.catalog.get("serve-web")
    assert runner.is_enabled(unit) is False
    enabled = runner.enable("serve-web", chroot="code")
    assert enabled["enabled"] is True
    assert runner.is_enabled(unit) is True
    disabled = runner.disable("serve-web", chroot="code")
    assert disabled["enabled"] is False
    assert runner.is_enabled(unit) is False


def test_service_runner_rejects_wrong_chroot(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from chrootctl.runtime.units import ServiceRunner

    service_dir = tmp_path / "services"
    service_dir.mkdir()
    _write_unit(service_dir, name="serve-web", chroot="code")
    cfg = ChrootConfig(service_dirs=(service_dir,), service_state_dir=tmp_path / "run", service_log_dir=tmp_path / "logs")
    context = SimpleNamespace(config=cfg, runner=SimpleNamespace(dry_run=False), logger=None)
    runner = ServiceRunner(context)

    with pytest.raises(RuntimeError, match="bound to chroot code"):
        runner.status("serve-web", chroot="alpine")


def test_dependency_layers_group_independent_units(tmp_path: Path) -> None:
    from chrootctl.runtime.units import ServiceCatalog, _dependency_layers

    service_dir = tmp_path / "services"
    service_dir.mkdir()
    _write_unit(service_dir, name="network-online")
    _write_unit(service_dir, name="db", body="After=network-online.service\nRequires=network-online.service")
    _write_unit(service_dir, name="api", body="After=db.service\nRequires=db.service")
    _write_unit(service_dir, name="worker", body="After=db.service\nRequires=db.service")
    cfg = ChrootConfig(service_dirs=(service_dir,), service_state_dir=tmp_path / "run", service_log_dir=tmp_path / "logs")
    graph = ServiceCatalog(cfg).by_name()

    assert _dependency_layers(graph) == [["network-online"], ["db"], ["api", "worker"]]


def test_load_service_unit_preserves_repeated_environment_lines(tmp_path: Path) -> None:
    unit_path = tmp_path / "vscode-web.service"
    unit_path.write_text(
        """
[Service]
Chroot=androidos
User=mike
Environment=HOST=0.0.0.0
Environment=PORT=8080
Environment=HOME=/home/mike USER=mike
ExecStart=code serve-web --host 0.0.0.0 --port 8080
""".strip()
        + "\n",
        encoding="utf-8",
    )

    unit = load_service_unit(unit_path)

    assert unit.environment == {"HOST": "0.0.0.0", "PORT": "8080", "HOME": "/home/mike", "USER": "mike"}


def test_service_script_preflights_identity_home_and_workdir(tmp_path: Path) -> None:
    from chrootctl.runtime.units import _service_script_text

    unit_path = tmp_path / "vscode-web.service"
    unit_path.write_text(
        """
[Service]
Chroot=androidos
User=mike
WorkingDirectory=/home/mike
Environment=HOME=/home/mike USER=mike
ExecStart=code serve-web --host 0.0.0.0 --port 8080
""".strip()
        + "\n",
        encoding="utf-8",
    )
    unit = load_service_unit(unit_path)

    script = _service_script_text(unit, service_user="mike")

    assert "[chrootctl-service] ===== preflight =====" in script
    assert "id=$(id" in script
    assert "groups mike" in script
    assert "ls -la /home/mike" in script
    assert "cd /home/mike" in script
    assert "exec code serve-web --host 0.0.0.0 --port 8080" in script
