from __future__ import annotations

import logging
from pathlib import Path

import pytest

from chrootctl.config import BindMount, ChrootConfig
from chrootctl.controller import ChrootController
from chrootctl.system import RunResult


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.mount_returncodes: dict[str, int] = {}
        self.dry_run = True

    def require_root(self) -> None:
        return None

    def mount_table(self) -> set[tuple[str, str]]:
        return set()

    def is_root(self) -> bool:
        return False

    def host_termux_uid_gid(self, termux_home: Path) -> tuple[int, int]:
        return (10123, 10123)

    def run(self, args, **kwargs) -> RunResult:
        argv = list(args)
        self.calls.append((argv, kwargs))
        stderr = ""
        returncode = 0
        if argv[:3] == ["busybox", "mount", "--bind"]:
            device = Path(argv[3]).name
            returncode = self.mount_returncodes.get(device, 0)
            if returncode:
                stderr = f"failed to bind {device}"
        if argv[:2] == ["busybox", "umount"]:
            device = Path(argv[2]).name
            returncode = self.mount_returncodes.get(f"umount:{device}", 0)
            if returncode:
                stderr = f"failed to unmount {device}"
        return RunResult(returncode=returncode, stdout="", stderr=stderr)


def build_controller(tmp_path: Path) -> tuple[ChrootController, FakeRunner]:
    cfg = ChrootConfig(chroot_root=tmp_path, termux_home=tmp_path / "termux-home", distro_name="ubuntu")
    runner = FakeRunner()
    return ChrootController(cfg, runner, logging.getLogger("test")), runner


def test_bind_host_devices_records_mount_failures(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)
    runner.mount_returncodes["tty"] = 1

    result = controller.bind_host_devices()

    assert result.failed == 1
    assert result.success >= 1
    assert "failed to bind tty" in result.errors


def test_start_login_opens_user_session(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)

    code = controller.start(login=True, root_login=False)

    assert code == 0
    argv, kwargs = runner.calls[-1]
    assert argv[-3:] == ["/bin/su", "-", "mike"]
    assert "-c" not in argv
    assert kwargs["env"]["USER"] == "mike"


def test_start_login_x11_prepares_host_and_exports_session_env(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)

    code = controller.start(login=True, root_login=False, x11=True)

    assert code == 0
    launch_calls = [call for call in runner.calls if call[0] and call[0][0] == "am"]
    assert launch_calls
    argv, kwargs = runner.calls[-1]
    assert argv[:4] == ["chroot", str(controller.config.chroot_base), "/bin/su", "-"]
    assert argv[-2:] == ["-c", "export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713; exec /usr/bin/zsh -il"]
    assert kwargs["env"]["DISPLAY"] == ":0"
    assert kwargs["env"]["PULSE_SERVER"] == "tcp:127.0.0.1:4713"


def test_start_defaults_to_root_login_shell(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)

    code = controller.start(login=False, root_login=False)

    assert code == 0
    argv, kwargs = runner.calls[-1]
    assert argv[:2] == ["chroot", str(controller.config.chroot_base)]
    assert argv[-2:] == ["/usr/bin/zsh", "-l"]
    assert kwargs["env"]["HOME"] == "/root"


def test_start_root_login_uses_login_shell(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)

    code = controller.start(login=False, root_login=True)

    assert code == 0
    argv, kwargs = runner.calls[-1]
    assert argv[:2] == ["chroot", str(controller.config.chroot_base)]
    assert argv[-2:] == ["/usr/bin/zsh", "-l"]
    assert kwargs["env"]["HOME"] == "/root"


def test_exec_runs_non_interactive_command(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)

    code = controller.exec(root=False, argv=["id", "-u"])

    assert code == 0
    argv, _ = runner.calls[-1]
    assert argv[-2:] == ["-c", "id -u"]


def test_exec_root_runs_via_shell_lc(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)

    code = controller.exec(root=True, command="id -u")

    assert code == 0
    argv, _ = runner.calls[-1]
    assert argv[-3:] == ["/usr/bin/zsh", "-lc", "id -u"]


def test_restart_unmounts_before_start(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)
    controller.unmount = lambda: runner.calls.append((["UNMOUNT"], {})) or None  # type: ignore[method-assign]

    code = controller.restart(login=True, root_login=False)

    assert code == 0
    assert runner.calls[0][0] == ["UNMOUNT"]


def test_doctor_reports_basic_checks(tmp_path: Path) -> None:
    controller, _ = build_controller(tmp_path)

    rows = controller.doctor()

    checks = {row["check"] for row in rows}
    assert {"busybox", "chroot", "shell", "chroot_base", "root", "mounts"} <= checks


def test_mount_uses_configured_media_mounts_and_optional_data_remount(tmp_path: Path) -> None:
    cfg = ChrootConfig(
        chroot_root=tmp_path,
        termux_home=tmp_path / "termux-home",
        distro_name="ubuntu",
        mount_data_with_dev_suid=False,
        media_mounts={"/storage/shared": "mnt/shared"},
    )
    runner = FakeRunner()
    runner.dry_run = False
    controller = ChrootController(cfg, runner, logging.getLogger("test"))

    result = controller.mount()

    assert result.failed == 0
    commands = [call[0] for call in runner.calls]
    assert ["busybox", "mount", "-o", "remount,dev,suid", "/data"] not in commands
    assert ["busybox", "mount", "--bind", "/storage/shared", str(cfg.chroot_base / "mnt/shared")] in commands
    assert (cfg.chroot_base / "mnt/shared").is_dir()


def test_mount_applies_read_only_remount_for_configured_mount(tmp_path: Path) -> None:
    cfg = ChrootConfig(
        chroot_root=tmp_path,
        termux_home=tmp_path / "termux-home",
        distro_name="ubuntu",
        media_mounts=(),
        extra_bind_mounts=(),
    ).with_overrides(
        extra_bind_mounts=(BindMount("/storage/shared", "mnt/shared", read_only=True),),
    )
    runner = FakeRunner()
    runner.dry_run = False
    controller = ChrootController(cfg, runner, logging.getLogger("test"))

    controller.mount()

    commands = [call[0] for call in runner.calls]
    assert ["busybox", "mount", "-o", "remount,bind,ro", str(cfg.chroot_base / "mnt/shared")] in commands


def test_exec_user_x11_wraps_command_with_login_shell_and_display_env(tmp_path: Path) -> None:
    controller, runner = build_controller(tmp_path)

    code = controller.exec(root=False, command="glxinfo", x11=True)

    assert code == 0
    argv, kwargs = runner.calls[-1]
    assert argv[:4] == ["chroot", str(controller.config.chroot_base), "/bin/su", "-"]
    assert "export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713;" in argv[-1]
    assert "exec /usr/bin/zsh -ilc glxinfo" in argv[-1]
    assert kwargs["env"]["DISPLAY"] == ":0"
