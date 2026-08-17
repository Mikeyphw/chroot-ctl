from __future__ import annotations

import logging
from pathlib import Path

import pytest

from chrootctl.arch import ArchInstaller
from chrootctl.base_install import BaseInstaller, ReleaseRef
from chrootctl.install_integrity import InstallFetchError
from chrootctl.config import ChrootConfig
from chrootctl.controller import ChrootController
from chrootctl.models import (
    InstallAlreadyCompleteResult,
    InstallBootstrapResult,
    InstallDesktopResult,
    InstallExtractResult,
    InstallFinalizeResult,
    UpgradeResult,
)
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

    def run_phase_extract(
        self,
        *,
        version: str | None,
        release: str | None,
        force_phase: bool = False,
    ) -> InstallExtractResult:
        self.called.append("extract")
        self.mark_phase("extract")
        return InstallExtractResult(version=version or "latest", release=release or "rolling", tarball="stub.tar.gz")

    def run_phase_bootstrap(
        self,
        *,
        username: str,
        profile: str | None = None,
        force_phase: bool = False,
    ) -> InstallBootstrapResult:
        self.called.append("bootstrap")
        self.mark_phase("bootstrap")
        return InstallBootstrapResult(username=username, profile=profile or "")

    def run_phase_desktop(
        self,
        *,
        desktop: str | None,
        profile: str | None = None,
        force_phase: bool = False,
    ) -> InstallDesktopResult:
        self.called.append("desktop")
        self.mark_phase("desktop")
        return InstallDesktopResult(desktop=desktop or "none", snapshot="", profile=profile or "")

    def run_phase_finalize(self, *, username: str, force_phase: bool = False) -> InstallFinalizeResult:
        self.called.append("finalize")
        self.mark_phase("finalize", installed=True)
        return InstallFinalizeResult(installed=True, uid_sync=True, snapshot="")

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


def test_install_without_phase_runs_remaining_phases_by_default(tmp_path: Path) -> None:
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
        profile="xfce4",
    )

    assert installer.called == ["extract", "bootstrap", "desktop", "finalize"]
    assert result == [
        InstallExtractResult(version="latest", release="rolling", tarball="stub.tar.gz"),
        InstallBootstrapResult(username="mike", profile="xfce4"),
        InstallDesktopResult(desktop="xfce4", snapshot="", profile="xfce4"),
        InstallFinalizeResult(installed=True, uid_sync=True, snapshot=""),
    ]


def test_explicit_phase_runs_single_phase_without_auto(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="extract")

    result = installer.install(
        phase="bootstrap",
        username="mike",
        desktop="xfce4",
        version=None,
        release=None,
        force_phase=False,
        auto=False,
        resume=False,
        repair=False,
        profile="xfce4",
    )

    assert installer.called == ["bootstrap"]
    assert result == [InstallBootstrapResult(username="mike", profile="xfce4")]


def test_explicit_phase_with_auto_runs_remaining_phases(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="extract")

    result = installer.install(
        phase="bootstrap",
        username="mike",
        desktop="xfce4",
        version=None,
        release=None,
        force_phase=False,
        auto=True,
        resume=False,
        repair=False,
        profile="xfce4",
    )

    assert installer.called == ["bootstrap", "desktop", "finalize"]
    assert result[0] == InstallBootstrapResult(username="mike", profile="xfce4")
    assert result[-1] == InstallFinalizeResult(installed=True, uid_sync=True, snapshot="")


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
        profile="xfce4",
    )

    assert installer.called == ["bootstrap", "desktop", "finalize"]
    assert result == [
        InstallBootstrapResult(username="mike", profile="xfce4"),
        InstallDesktopResult(desktop="xfce4", snapshot="", profile="xfce4"),
        InstallFinalizeResult(installed=True, uid_sync=True, snapshot=""),
    ]


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
    assert result == [InstallAlreadyCompleteResult()]


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

    assert installer.called == ["extract", "bootstrap", "desktop", "finalize"]
    assert result[0] == InstallExtractResult(version="latest", release="rolling", tarball="stub.tar.gz")
    assert result[1] == InstallBootstrapResult(username="mike", profile="dev")
    assert result[2] == InstallDesktopResult(desktop="none", snapshot="", profile="dev")


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

    assert installer.called == ["desktop", "finalize"]
    assert result == [
        InstallDesktopResult(desktop="none", snapshot="", profile="minimal"),
        InstallFinalizeResult(installed=True, uid_sync=True, snapshot=""),
    ]


def test_repair_reruns_extract_when_bootstrap_is_not_ready(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="bootstrap")
    installer.ready_for_bootstrap = lambda: False  # type: ignore[method-assign]

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

    assert installer.called == ["extract", "bootstrap", "desktop", "finalize"]
    assert result[0] == InstallExtractResult(version="latest", release="rolling", tarball="stub.tar.gz")
    assert result[-1] == InstallFinalizeResult(installed=True, uid_sync=True, snapshot="")


def test_upgrade_runs_installer_upgrade_flow(tmp_path: Path) -> None:
    installer, _ = build_stub_installer(tmp_path)

    result = installer.upgrade()

    assert installer.called == ["upgrade"]
    assert result == UpgradeResult(status="upgraded", snapshot="")


def test_chroot_shell_uses_sanitized_environment(tmp_path: Path) -> None:
    installer, _ = build_stub_installer(tmp_path)

    installer._chroot_shell("true")

    assert installer.runner.kwargs[-1]["chroot_env"] is True


def test_require_chroot_commands_uses_sanitized_environment(tmp_path: Path) -> None:
    installer, _ = build_stub_installer(tmp_path)

    installer._require_chroot_commands("apt")

    assert installer.runner.commands[-1][-1] == "command -v apt >/dev/null 2>&1"
    assert installer.runner.kwargs[-1]["chroot_env"] is True


def test_ubuntu_bootstrap_installs_prerequisites_before_group_setup(tmp_path: Path) -> None:
    installer, runner = build_real_installer(UbuntuInstaller, tmp_path)
    (installer.config.chroot_base / "usr/bin").mkdir(parents=True)
    (installer.config.chroot_base / "usr/bin/apt").touch()

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

    assert result.phase == "bootstrap"
    assert apt_update_index < prereq_index < preflight_index < group_index
    assert "passwd login libc-bin sudo" in shell_commands[prereq_index]


def test_ubuntu_default_install_reruns_extract_when_apt_is_missing(tmp_path: Path) -> None:
    installer, _ = build_real_installer(UbuntuInstaller, tmp_path)
    installer.registry.upsert(name="ubuntu", distro="ubuntu", path=str(installer.config.chroot_base), phase="extract")
    (installer.config.chroot_base / "etc").mkdir(parents=True)
    (installer.config.chroot_base / "etc/os-release").write_text("ID=ubuntu\n", encoding="utf-8")
    installer._resolve_release = lambda version, release: ReleaseRef("noble", "https://example.invalid/release/")  # type: ignore[method-assign]
    installer._resolve_tarball = lambda ref: ("ubuntu-base.tar.gz", "https://example.invalid/ubuntu-base.tar.gz")  # type: ignore[method-assign]

    result = installer.install(
        phase=None,
        username="mike",
        desktop=None,
        version=None,
        release=None,
        force_phase=False,
        auto=False,
        resume=False,
        repair=False,
        profile=None,
    )

    assert result[0].phase == "extract"
    assert any(command[:2] == ["curl", "--fail"] for command in installer.runner.commands)
    curl_index = next(index for index, command in enumerate(installer.runner.commands) if command[:2] == ["curl", "--fail"])
    assert "--location" in installer.runner.commands[curl_index]
    assert "-o" in installer.runner.commands[curl_index]
    assert installer.runner.kwargs[curl_index]["capture_output"] is False
    assert not any(command and command[0] == "tar" for command in installer.runner.commands)


def test_ubuntu_default_install_recovers_from_bootstrap_registry_when_apt_is_missing(tmp_path: Path) -> None:
    installer, _ = build_real_installer(UbuntuInstaller, tmp_path)
    installer.registry.upsert(name="ubuntu", distro="ubuntu", path=str(installer.config.chroot_base), phase="bootstrap")
    (installer.config.chroot_base / "etc").mkdir(parents=True)
    (installer.config.chroot_base / "etc/os-release").write_text("ID=ubuntu\n", encoding="utf-8")
    installer._resolve_release = lambda version, release: ReleaseRef("noble", "https://example.invalid/release/")  # type: ignore[method-assign]
    installer._resolve_tarball = lambda ref: ("ubuntu-base.tar.gz", "https://example.invalid/ubuntu-base.tar.gz")  # type: ignore[method-assign]

    result = installer.install(
        phase=None,
        username="mike",
        desktop=None,
        version=None,
        release=None,
        force_phase=False,
        auto=False,
        resume=False,
        repair=False,
        profile=None,
    )

    assert result[0].phase == "extract"


def test_arch_extract_dry_run_reports_download_without_extracting(tmp_path: Path) -> None:
    installer, runner = build_real_installer(ArchInstaller, tmp_path)

    result = installer.run_phase_extract(version=None, release=None, force_phase=True)

    curl_index = next(index for index, command in enumerate(runner.commands) if command[:2] == ["curl", "--fail"])
    assert result.phase == "extract"
    assert runner.kwargs[curl_index]["capture_output"] is False
    assert not any(command and command[0] == "bsdtar" for command in runner.commands)
    assert installer.registry.get(installer.config.distro_name) is None


def test_default_profile_is_minimal_and_default_desktop_is_none(tmp_path: Path) -> None:
    installer, _ = build_stub_installer(tmp_path)

    assert installer._selected_profile(None) == "minimal"
    assert installer._selected_desktop(None, None) == "none"


def test_minimal_profile_rejects_explicit_desktop(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="extract")

    with pytest.raises(ValueError, match="minimal profile does not allow desktop"):
        installer.install(
            phase=None,
            username="mike",
            desktop="xfce4",
            version=None,
            release=None,
            force_phase=False,
            auto=False,
            resume=False,
            repair=False,
            profile="minimal",
        )


def test_minimal_profile_forces_auto_desktop_to_none(tmp_path: Path) -> None:
    installer, registry = build_stub_installer(tmp_path)
    registry.upsert(name="stub", distro="stub", path="/tmp/stub", phase="bootstrap")

    result = installer.install(
        phase=None,
        username="mike",
        desktop="auto",
        version=None,
        release=None,
        force_phase=False,
        auto=False,
        resume=False,
        repair=False,
        profile="minimal",
    )

    assert result == [
        InstallBootstrapResult(username="mike", profile="minimal"),
        InstallDesktopResult(desktop="none", snapshot="", profile="minimal"),
        InstallFinalizeResult(installed=True, uid_sync=True, snapshot=""),
    ]


def test_ubuntu_desktop_phase_installs_light_packages_not_flavor_metapackage(tmp_path: Path) -> None:
    installer, runner = build_real_installer(UbuntuInstaller, tmp_path)
    (installer.config.chroot_base / "etc").mkdir(parents=True)

    result = installer.run_phase_desktop(desktop="xfce4", profile="xfce4", force_phase=True)

    shell_commands = [
        command[-1]
        for command in runner.commands
        if command[:4] == ["busybox", "chroot", str(installer.config.chroot_base), "/bin/bash"]
    ]
    install_command = next(command for command in shell_commands if "apt install" in command)
    assert result.desktop == "xfce4"
    assert "--no-install-recommends" in install_command
    assert " xfce4 " in f" {install_command} "
    assert "xubuntu-desktop" not in install_command
    assert "kubuntu-desktop" not in install_command


def test_foreign_arch_upgrade_allows_qemu_binfmt_support(tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", database_path=tmp_path / "db.sqlite3", distro_name="work", username="mike", target_arch="arm64")
    registry = ChrootRegistry(config.database_path)
    runner = InstallerRunner()
    runner.host_arch = lambda: "amd64"
    runner.can_execute_foreign_arch = lambda arch: arch == "arm64"
    controller = ChrootController(config, runner, logging.getLogger("test"))
    user_sync = UserSyncManager(config, runner, logging.getLogger("test"))
    installer = StubInstaller(config, runner, controller, registry, user_sync, logging.getLogger("test"))

    result = installer.upgrade()

    assert result.status == "upgraded"


def test_foreign_arch_upgrade_requires_emulation_without_qemu(tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", database_path=tmp_path / "db.sqlite3", distro_name="work", username="mike", target_arch="arm64")
    registry = ChrootRegistry(config.database_path)
    runner = InstallerRunner()
    runner.host_arch = lambda: "amd64"
    runner.can_execute_foreign_arch = lambda arch: False
    controller = ChrootController(config, runner, logging.getLogger("test"))
    user_sync = UserSyncManager(config, runner, logging.getLogger("test"))
    installer = StubInstaller(config, runner, controller, registry, user_sync, logging.getLogger("test"))

    with pytest.raises(RuntimeError, match="enable binfmt_misc"):
        installer.upgrade()


def test_base_installer_download_retries_alternate_mirrors(tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", database_path=tmp_path / "db.sqlite3", distro_name="work", username="mike")
    registry = ChrootRegistry(config.database_path)
    runner = InstallerRunner()
    controller = ChrootController(config, runner, logging.getLogger("test"))
    user_sync = UserSyncManager(config, runner, logging.getLogger("test"))
    installer = StubInstaller(config, runner, controller, registry, user_sync, logging.getLogger("test"))
    installer.configure_mirror_plan(
        selection="mirror-a",
        base_url="https://mirror-a.example",
        candidates=(
            {"id": "mirror-a", "url": "https://mirror-a.example"},
            {"id": "mirror-b", "url": "https://mirror-b.example"},
        ),
    )

    attempts: list[str] = []

    def fake_download(url: str, target: Path) -> None:
        attempts.append(url)
        if "mirror-a" in url:
            raise InstallFetchError("primary down")

    installer._download = fake_download  # type: ignore[method-assign]

    resolved = installer._download_with_mirror_fallback("https://mirror-a.example/releases/rootfs.tar.gz", tmp_path / "rootfs.tar.gz")

    assert attempts == [
        "https://mirror-a.example/releases/rootfs.tar.gz",
        "https://mirror-b.example/releases/rootfs.tar.gz",
    ]
    assert resolved == "https://mirror-b.example/releases/rootfs.tar.gz"


def test_ubuntu_apt_commands_retry_alternate_mirrors(tmp_path: Path) -> None:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", database_path=tmp_path / "db.sqlite3", distro_name="work", username="mike", target_arch="arm64")
    registry = ChrootRegistry(config.database_path)
    runner = InstallerRunner()
    controller = ChrootController(config, runner, logging.getLogger("test"))
    user_sync = UserSyncManager(config, runner, logging.getLogger("test"))
    installer = UbuntuInstaller(config, runner, controller, registry, user_sync, logging.getLogger("test"))
    installer.configure_mirror_plan(
        selection="archive.ubuntu.com",
        base_url="https://archive.ubuntu.com/ubuntu",
        candidates=(
            {"id": "archive.ubuntu.com", "url": "https://archive.ubuntu.com/ubuntu"},
            {"id": "ports.ubuntu.com", "url": "https://ports.ubuntu.com/ubuntu-ports"},
        ),
    )

    commands: list[str] = []
    responses = iter((
        RunResult(returncode=1, stdout="", stderr="Temporary failure resolving archive.ubuntu.com"),
        RunResult(returncode=0, stdout="", stderr=""),
    ))
    installer._chroot_shell = lambda command: commands.append(command)  # type: ignore[method-assign]
    installer._chroot_shell_result = lambda command: commands.append(command) or next(responses)  # type: ignore[method-assign]

    installer._apt_with_mirror_fallback("apt update")

    assert any("archive.ubuntu.com/ubuntu" in command for command in commands)
    assert any("ports.ubuntu.com/ubuntu-ports" in command for command in commands)
    assert commands.count("apt update") == 2
