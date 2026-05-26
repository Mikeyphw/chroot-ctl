from __future__ import annotations

import logging
from pathlib import Path

import pytest

from chrootctl.arch import ArchInstaller
from chrootctl.base_install import BaseInstaller, ReleaseRef
from chrootctl.config import ChrootConfig
from chrootctl.controller import ChrootController
from chrootctl.registry import ChrootRegistry
from chrootctl.system import RunResult
from chrootctl.ubuntu import UbuntuInstaller
from chrootctl.user_sync import UserSyncManager


class InstallerRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.dry_run = True

    def require_root(self) -> None:
        return None

    def run(self, args, **kwargs) -> RunResult:
        self.commands.append(list(args))
        self.kwargs.append(kwargs)
        return RunResult(returncode=0, stdout="", stderr="")

    def mount_table(self) -> set[tuple[str, str]]:
        return set()

    def host_termux_uid_gid(self, termux_home: Path) -> tuple[int, int]:
        return (2000, 2000)


class StubInstaller(BaseInstaller):
    distro = "stub"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.called: list[str] = []

    def list_versions(self) -> list[ReleaseRef]:
        return [ReleaseRef("latest", "http://example.invalid/rootfs.tar.gz")]

    def infer_phase_from_filesystem(self):
        return "extract"

    def run_phase_extract(self, *, version: str | None, release: str | None, force_phase: bool = False) -> dict[str, str]:
        self.called.append("extract")
        self.mark_phase("extract")
        return {"phase": "extract"}

    def run_phase_bootstrap(self, *, username: str, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        self.called.append("bootstrap")
        self.mark_phase("bootstrap")
        return {"phase": "bootstrap", "profile": profile or ""}

    def run_phase_desktop(self, *, desktop: str | None, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        self.called.append("desktop")
        self.mark_phase("desktop")
        return {"phase": "desktop", "desktop": desktop or "none", "profile": profile or ""}

    def run_phase_finalize(self, *, username: str, force_phase: bool = False) -> dict[str, str]:
        self.called.append("finalize")
        self.mark_phase("finalize", installed=True)
        return {"phase": "finalize"}

    def _run_upgrade(self) -> None:
        self.called.append("upgrade")


def build_stub_installer(tmp_path: Path) -> tuple[StubInstaller, ChrootRegistry]:
    cfg = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="stub")
    runner = InstallerRunner()
    logger = logging.getLogger("test")
    registry = ChrootRegistry(tmp_path / "registry.sqlite3")
    controller = ChrootController(cfg, runner, logger)
    user_sync = UserSyncManager(cfg, runner, logger)
    return StubInstaller(cfg, runner, controller, registry, user_sync, logger), registry


def build_real_installer(installer_cls, tmp_path: Path):
    cfg = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu")
    runner = InstallerRunner()
    logger = logging.getLogger("test")
    registry = ChrootRegistry(tmp_path / f"{installer_cls.__name__}.sqlite3")
    controller = ChrootController(cfg, runner, logger)
    user_sync = UserSyncManager(cfg, runner, logger)
    return installer_cls(cfg, runner, controller, registry, user_sync, logger), runner


def test_manual_install_without_phase_uses_next_actionable_phase(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="extract")

    result = installer.install(
        phase=None,
        username="mike",
        desktop="xfce4",
        version=None,
        release=None,
        force_phase=False,
        auto=False,
        resume=False,
        repair=False,
        profile=None,
    )

    assert installer.called == ["bootstrap"]
    assert result == [{"phase": "bootstrap", "profile": "xfce4"}]


def test_auto_install_runs_remaining_phases(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="bootstrap")

    result = installer.install(
        phase=None,
        username="mike",
        desktop="xfce4",
        version=None,
        release=None,
        force_phase=False,
        auto=True,
        resume=False,
        repair=False,
        profile=None,
    )

    assert installer.called == ["desktop", "finalize"]
    assert result == [{"phase": "desktop", "desktop": "xfce4", "profile": "xfce4"}, {"phase": "finalize"}]


def test_auto_install_short_circuits_when_already_installed(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="finalize", installed=True)

    result = installer.install(
        phase=None,
        username="mike",
        desktop="xfce4",
        version=None,
        release=None,
        force_phase=False,
        auto=True,
        resume=False,
        repair=False,
        profile=None,
    )

    assert installer.called == []
    assert result == [{"phase": "finalize", "installed": "true", "status": "already_complete"}]


@pytest.mark.parametrize("installer_cls", [UbuntuInstaller, ArchInstaller])
def test_installers_reject_invalid_username(tmp_path: Path, installer_cls) -> None:
    installer, runner = build_real_installer(installer_cls, tmp_path)

    with pytest.raises(ValueError, match="invalid username"):
        installer.run_phase_bootstrap(username="mike;id", profile="dev", force_phase=True)

    assert runner.commands == []


def test_resume_runs_remaining_phases(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="extract")

    result = installer.install(
        phase=None,
        username="mike",
        desktop=None,
        version=None,
        release=None,
        force_phase=False,
        auto=False,
        resume=True,
        repair=False,
        profile="dev",
    )

    assert installer.called == ["bootstrap", "desktop", "finalize"]
    assert result[0]["profile"] == "dev"
    assert result[1]["desktop"] == "none"


def test_repair_reruns_current_phase(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="desktop")

    result = installer.install(
        phase=None,
        username="mike",
        desktop=None,
        version=None,
        release=None,
        force_phase=False,
        auto=False,
        resume=False,
        repair=True,
        profile="minimal",
    )

    assert installer.called == ["desktop"]
    assert result == [{"phase": "desktop", "desktop": "none", "profile": "minimal"}]


def test_upgrade_runs_installer_upgrade_flow(tmp_path: Path) -> None:
    installer, _ = build_stub_installer(tmp_path)

    result = installer.upgrade()

    assert installer.called == ["upgrade"]
    assert result["status"] == "upgraded"


def test_chroot_shell_uses_sanitized_environment(tmp_path: Path) -> None:
    installer, _ = build_stub_installer(tmp_path)

    installer._chroot_shell("true")

    assert installer.runner.kwargs[-1]["chroot_env"] is True


def test_ubuntu_bootstrap_installs_prerequisites_before_group_setup(tmp_path: Path) -> None:
    installer, runner = build_real_installer(UbuntuInstaller, tmp_path)

    result = installer.run_phase_bootstrap(username="mike", profile="minimal", force_phase=True)

    shell_commands = [
        command[-1]
        for command in runner.commands
        if command[:4] == ["busybox", "chroot", str(installer.config.chroot_base), "/bin/bash"]
    ]
    apt_update_index = shell_commands.index("apt update")
    prereq_index = next(
        index
        for index, command in enumerate(shell_commands)
        if command.startswith("DEBIAN_FRONTEND=noninteractive apt install -y passwd login libc-bin sudo")
    )
    group_index = next(index for index, command in enumerate(shell_commands) if "getent group aid_inet" in command)
    preflight_index = next(index for index, command in enumerate(shell_commands) if "command -v groupadd" in command)

    assert result["phase"] == "bootstrap"
    assert apt_update_index < prereq_index < preflight_index < group_index
    assert "passwd login libc-bin sudo" in shell_commands[prereq_index]
