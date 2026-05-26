from __future__ import annotations

import logging
from pathlib import Path

import pytest

from chrootctl.config import ChrootConfig
from chrootctl.system import RunResult
from chrootctl.user_sync import UserSyncManager


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []

    def require_root(self) -> None:
        return None

    def host_termux_uid_gid(self, termux_home: Path) -> tuple[int, int]:
        return (2000, 2000)

    def run(self, args, **kwargs) -> RunResult:
        self.commands.append(list(args))
        self.kwargs.append(kwargs)
        return RunResult(returncode=0, stdout="", stderr="")


def build_manager(tmp_path: Path) -> tuple[UserSyncManager, RecordingRunner]:
    cfg = ChrootConfig(chroot_root=tmp_path, termux_home=tmp_path, distro_name="ubuntu")
    runner = RecordingRunner()
    return UserSyncManager(cfg, runner, logging.getLogger("test")), runner


def test_show_id_reads_paths(tmp_path: Path) -> None:
    cfg = ChrootConfig(chroot_root=tmp_path, termux_home=tmp_path, distro_name="ubuntu")
    (cfg.chroot_base / "etc").mkdir(parents=True)
    (cfg.chroot_base / "etc/passwd").write_text("mike:x:1000:1000::/home/mike:/bin/bash\n", encoding="utf-8")
    mgr = UserSyncManager(cfg, RecordingRunner(), logging.getLogger("test"))
    data = mgr.show_id("mike")
    assert data["username"] == "mike"


def test_sync_id_uses_quoted_username_and_paths(tmp_path: Path) -> None:
    mgr, runner = build_manager(tmp_path)

    result = mgr.sync_id("mike", fix_ownership=True)

    assert result["ownership_fixed"] == "yes"
    commands = [cmd[-1] for cmd in runner.commands]
    assert "groupadd mike" in commands[0]
    assert "useradd -m -s /bin/bash mike" in commands[1]
    assert '[ -e /home/mike ] && chown -R 2000:2000 /home/mike || true' in commands[4]


@pytest.mark.parametrize("username", ["mike;id", "mike name", "mike$(id)"])
def test_sync_id_rejects_invalid_username(tmp_path: Path, username: str) -> None:
    mgr, runner = build_manager(tmp_path)

    with pytest.raises(ValueError, match="invalid username"):
        mgr.sync_id(username)

    assert runner.commands == []


def test_sync_id_can_skip_ownership_fix(tmp_path: Path) -> None:
    mgr, runner = build_manager(tmp_path)

    result = mgr.sync_id("mike", fix_ownership=False)

    assert result["ownership_fixed"] == "no"
    assert len(runner.commands) == 4


def test_sync_id_uses_sanitized_chroot_environment(tmp_path: Path) -> None:
    mgr, runner = build_manager(tmp_path)

    mgr.sync_id("mike", fix_ownership=False)

    assert runner.kwargs
    assert all(kwargs.get("chroot_env") is True for kwargs in runner.kwargs)
