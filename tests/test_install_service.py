
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from chrootctl.config import ChrootConfig
from chrootctl.models import InstallRequest, InstallFinalizeResult
from chrootctl.registry import ChrootRegistry
from chrootctl.services.install import InstallService


class FakeRunner:
    def host_arch(self):
        return "arm64"

    def command_exists(self, command: str) -> bool:
        return True

    def can_execute_foreign_arch(self, target_arch: str) -> bool:
        return target_arch == "arm64"


class FakeServices:
    def __init__(self, tmp_path: Path) -> None:
        self.base_config = ChrootConfig(
            chroot_root=tmp_path / "chroots",
            database_path=tmp_path / "registry.sqlite3",
            log_file=tmp_path / "chrootctl.log",
            distro_name="ubuntu",
            username=None,
        )
        self.registry = ChrootRegistry(self.base_config.database_path)
        self.logger = SimpleNamespace(info=lambda *args, **kwargs: None)

    def runtime_for(self, name: str | None = None, username: str | None = None):
        config = self.base_config.with_overrides(distro_name=name or "ubuntu", username=username)
        return SimpleNamespace(
            config=config,
            runner=FakeRunner(),
            controller=SimpleNamespace(),
            user_sync=SimpleNamespace(),
        )

    def config_for(self, name: str):
        return self.base_config.with_overrides(distro_name=name)

    def chroots(self):
        return SimpleNamespace(list=lambda: [])

    def catalog(self, kind: str, name: str | None = None):
        return SimpleNamespace(apply=lambda names: [])

    def users(self, name: str | None = None):
        return SimpleNamespace(list=lambda: [])

    def system(self):
        from chrootctl.services.system import SystemService
        return SystemService(self)

    def install(self):
        return InstallService(self)


def test_validate_install_submission_uses_default_username(tmp_path: Path):
    service = InstallService(FakeServices(tmp_path))
    result = service.validate_install_submission(
        InstallRequest(distro="ubuntu", name="ubuntu", username="", preset="minimal-server")
    )
    assert result["ok"] is True
    assert result["requirements"]["default_username"] == "mike"
    assert result["requirements"]["default_username"] == "mike"
    assert result["ok"] is True


def test_install_uses_keyword_build_installer_args(monkeypatch, tmp_path: Path):
    service = InstallService(FakeServices(tmp_path))
    captured = {}

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    def fake_build_installer(distro, **kwargs):
        captured["distro"] = distro
        captured.update(kwargs)
        return Installer()

    monkeypatch.setattr("chrootctl.services.install.build_installer", fake_build_installer)

    result = service.install(
        InstallRequest(distro="ubuntu", name="ubuntu", username="", preset="minimal-server")
    )

    assert result.chroot_name == "ubuntu"
    assert captured["config"].username == "mike"
    assert "runner" in captured and "controller" in captured and "registry" in captured and "user_sync" in captured and "logger" in captured
