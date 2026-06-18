from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from chrootctl.services.install import InstallService
from chrootctl.services.system import SystemService


class FakeRegistry:
    def __init__(self, rows):
        self._rows = list(rows)

    def list(self):
        return list(self._rows)

    def get(self, name: str):
        for row in self._rows:
            if row.get("name") == name:
                return row
        return None


class FakeRuntime:
    def __init__(self, usernames):
        self.chroot_users = SimpleNamespace(user_rows=lambda: [SimpleNamespace(username=name, uid=1000 + index) for index, name in enumerate(usernames)])
        self.controller = SimpleNamespace(status=lambda verbose=False: [], doctor=lambda: [])
        self.config = SimpleNamespace(distro_name="ubuntu", log_file=Path("/tmp/chrootctl.log"))


class FakeServices:
    def __init__(self, rows, usernames, configured_username="root"):
        self.registry = FakeRegistry(rows)
        self.base_config = SimpleNamespace(username=configured_username)
        self._runtime = FakeRuntime(usernames)

    def runtime_for(self, name=None, *, username=None):
        return self._runtime

    def config_for(self, name=None):
        return self._runtime.config


def test_install_service_prefers_registry_defaults_and_single_user_hint(monkeypatch) -> None:
    services = FakeServices(
        rows=[
            {
                "name": "work",
                "distro": "ubuntu",
                "release_name": "jammy",
                "version": "latest",
                "installed": False,
                "metadata": {"profile": "dev", "desktop": "xfce4"},
            }
        ],
        usernames=["alice"],
    )
    monkeypatch.setenv("USER", "")
    defaults = InstallService(services).wizard_defaults()
    assert defaults.name == "work"
    assert defaults.distro == "ubuntu"
    assert defaults.profile == "dev"
    assert defaults.desktop == "xfce4"
    assert defaults.username == "alice"


def test_system_service_logs_shapes_entries_and_links(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "chrootctl.log"
    log_path.write_text("2026-06-18 INFO applied tool tool-one\n2026-06-18 ERROR failed\n", encoding="utf-8")
    services = FakeServices(rows=[{"name": "work", "installed": True, "distro": "ubuntu", "phase": "finalize"}], usernames=["alice"])
    services._runtime.config = SimpleNamespace(distro_name="ubuntu", log_file=log_path)
    snapshot = SystemService(services).logs("work")
    assert snapshot.log_file == log_path
    assert snapshot.level is None
    assert snapshot.entries[0].links[0].href == "/tools/tool-one"
    assert snapshot.related_links[0].href == "/chroots/work"
