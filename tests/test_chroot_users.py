from __future__ import annotations

import logging
from pathlib import Path

import pytest

from chrootctl.chroot_users import ChrootUserManager
from chrootctl.config import ChrootConfig
from chrootctl.registry import ChrootRegistry
from chrootctl.system import RunResult


class RecordingRunner:
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


def build_manager(tmp_path: Path, *, installed: bool = True) -> tuple[ChrootUserManager, ChrootConfig, RecordingRunner, ChrootRegistry]:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", distro_name="ubuntu")
    runner = RecordingRunner()
    registry = ChrootRegistry(tmp_path / "registry.sqlite3")
    if installed:
        registry.upsert(
            name="ubuntu",
            distro="ubuntu",
            path=str(config.chroot_base),
            phase="finalize",
            installed=True,
        )
    manager = ChrootUserManager(config, runner, registry, logging.getLogger("test"))
    return manager, config, runner, registry


def write_passwd(config: ChrootConfig) -> None:
    (config.chroot_base / "etc").mkdir(parents=True)
    (config.chroot_base / "etc/passwd").write_text(
        "\n".join(
            [
                "root:x:0:0:root:/root:/bin/bash",
                "mike:x:2000:2000::/home/mike:/usr/bin/zsh",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_list_and_show_users_parse_passwd(tmp_path: Path) -> None:
    manager, config, _, _ = build_manager(tmp_path)
    write_passwd(config)

    rows = manager.user_rows()
    data = manager.show_user("mike")

    assert [row.username for row in rows] == ["root", "mike"]
    assert data.uid == "2000"
    assert data.shell == "/usr/bin/zsh"


def test_show_user_reports_sudo_yes_when_sudoers_fragment_matches(tmp_path: Path) -> None:
    manager, config, _, _ = build_manager(tmp_path)
    write_passwd(config)
    sudoers = config.chroot_base / "etc" / "sudoers.d" / "90-chrootctl-mike"
    sudoers.parent.mkdir(parents=True)
    sudoers.write_text("mike ALL=(ALL:ALL) ALL\n", encoding="utf-8")

    data = manager.show_user("mike")

    assert data.sudo is True
    assert data.to_display_dict()["sudo"] == "yes"


def test_show_user_reports_sudo_no_when_sudoers_fragment_is_missing_or_invalid(tmp_path: Path) -> None:
    manager, config, _, _ = build_manager(tmp_path)
    write_passwd(config)

    missing = manager.show_user("mike")
    assert missing.sudo is False
    assert missing.to_display_dict()["sudo"] == "no"

    sudoers = config.chroot_base / "etc" / "sudoers.d" / "90-chrootctl-mike"
    sudoers.parent.mkdir(parents=True)
    sudoers.write_text("mike ALL=(ALL) NOPASSWD: /usr/bin/id\n", encoding="utf-8")

    invalid = manager.show_user("mike")

    assert invalid.sudo is False
    assert invalid.to_display_dict()["sudo"] == "no"


def test_add_user_generates_sanitized_chroot_commands(tmp_path: Path) -> None:
    manager, _, runner, _ = build_manager(tmp_path)

    result = manager.add_user("mike", shell="/bin/zsh", sudo=True)

    assert result.created is True
    commands = [command[-1] for command in runner.commands if command[-2:] != ["passwd", "mike"]]
    assert any("groupadd mike" in command for command in commands)
    assert any("useradd -m -s /bin/zsh -g mike mike" in command for command in commands)
    assert any("usermod -aG sudo mike" in command for command in commands)
    assert all(kwargs.get("chroot_env") is True for kwargs in runner.kwargs)


def test_remove_password_shell_and_sudo_commands(tmp_path: Path) -> None:
    manager, config, runner, _ = build_manager(tmp_path)
    write_passwd(config)

    manager.remove_user("mike", delete_home=True)
    manager.set_password("mike")
    manager.set_shell("mike", shell="/usr/bin/zsh")
    manager.set_sudo("mike", enabled=False)

    joined = "\n".join(" ".join(command) for command in runner.commands)
    assert "userdel -r mike" in joined
    assert "busybox chroot" in joined
    assert " passwd mike" in joined
    assert "usermod -s /usr/bin/zsh mike" in joined
    assert "gpasswd -d mike sudo" in joined
    assert all(kwargs.get("chroot_env") is True for kwargs in runner.kwargs)


def test_mutating_commands_require_installed_chroot(tmp_path: Path) -> None:
    manager, _, runner, _ = build_manager(tmp_path, installed=False)

    with pytest.raises(RuntimeError, match="installed first"):
        manager.add_user("mike", shell="/bin/bash", sudo=False)

    assert runner.commands == []


@pytest.mark.parametrize("username", ["bad user", "bad;id", "bad$(id)"])
def test_mutating_commands_reject_invalid_usernames(tmp_path: Path, username: str) -> None:
    manager, _, runner, _ = build_manager(tmp_path)

    with pytest.raises(ValueError, match="invalid username"):
        manager.add_user(username, shell="/bin/bash", sudo=False)

    assert runner.commands == []
