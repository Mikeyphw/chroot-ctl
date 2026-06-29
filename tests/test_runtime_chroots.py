from __future__ import annotations

import logging
from pathlib import Path

import pytest

from chrootctl.config import ChrootConfig
from chrootctl.registry import ChrootRegistry
from chrootctl.runtime.chroots import remove_chroot, rename_chroot
from chrootctl.system import RunResult


class Runner:
    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.commands: list[list[str]] = []

    def require_root(self) -> None:
        return None

    def mount_table(self) -> set[tuple[str, str]]:
        return set()

    def run(self, args, **kwargs) -> RunResult:
        self.commands.append(list(args))
        return RunResult(returncode=0, stdout="", stderr="")


def build_context(tmp_path: Path) -> tuple[ChrootConfig, ChrootRegistry, logging.Logger]:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", database_path=tmp_path / "registry.sqlite3")
    registry = ChrootRegistry(config.database_path)
    logger = logging.getLogger("test")
    return config, registry, logger


def test_remove_chroot_requires_registry_record(tmp_path: Path) -> None:
    config, registry, logger = build_context(tmp_path)
    runner = Runner(dry_run=False)

    with pytest.raises(RuntimeError, match="no registry record"):
        remove_chroot(config, registry, runner, logger, "missing")


def test_remove_chroot_dry_run_preserves_registry_and_filesystem(tmp_path: Path) -> None:
    config, registry, logger = build_context(tmp_path)
    runner = Runner(dry_run=True)
    target = config.for_chroot("ubuntu").chroot_base
    target.mkdir(parents=True)
    registry.upsert(name="ubuntu", distro="ubuntu", path=str(target), phase="finalize", installed=True)

    result = remove_chroot(config, registry, runner, logger, "ubuntu")

    assert result.removed is False
    assert target.exists()
    assert registry.get("ubuntu") is not None


def test_remove_chroot_deletes_registry_and_filesystem(tmp_path: Path) -> None:
    config, registry, logger = build_context(tmp_path)
    runner = Runner(dry_run=False)
    target = config.for_chroot("ubuntu").chroot_base
    target.mkdir(parents=True)
    registry.upsert(name="ubuntu", distro="ubuntu", path=str(target), phase="finalize", installed=True)

    result = remove_chroot(config, registry, runner, logger, "ubuntu")

    assert result.removed is True
    assert not target.exists()
    assert registry.get("ubuntu") is None


def test_rename_chroot_rejects_existing_destination(tmp_path: Path) -> None:
    config, registry, _ = build_context(tmp_path)
    old_target = config.for_chroot("old").chroot_base
    old_target.mkdir(parents=True)
    registry.upsert(name="old", distro="ubuntu", path=str(old_target), phase="finalize", installed=True)
    new_target = config.for_chroot("new").chroot_base
    registry.upsert(name="new", distro="ubuntu", path=str(new_target), phase="finalize", installed=True)

    with pytest.raises(RuntimeError, match="destination chroot already exists"):
        rename_chroot(config, registry, "old", "new")


@pytest.mark.parametrize("name", ["", "   ", "../bad", "bad/name", "bad name"])
def test_rename_chroot_rejects_invalid_destination_name(tmp_path: Path, name: str) -> None:
    config, registry, _ = build_context(tmp_path)
    old_target = config.for_chroot("old").chroot_base
    old_target.mkdir(parents=True)
    registry.upsert(name="old", distro="ubuntu", path=str(old_target), phase="finalize", installed=True)

    with pytest.raises(RuntimeError, match="invalid chroot name|new chroot name is required"):
        rename_chroot(config, registry, "old", name)


def test_rename_chroot_rejects_registry_path_mismatch(tmp_path: Path) -> None:
    config, registry, _ = build_context(tmp_path)
    expected = config.for_chroot("old").chroot_base
    expected.mkdir(parents=True)
    mismatched = tmp_path / "elsewhere" / "old"
    registry.upsert(name="old", distro="ubuntu", path=str(mismatched), phase="finalize", installed=True)

    with pytest.raises(RuntimeError, match="registry path mismatch"):
        rename_chroot(config, registry, "old", "new")


def test_rename_chroot_moves_filesystem_and_registry(tmp_path: Path) -> None:
    config, registry, _ = build_context(tmp_path)
    old_target = config.for_chroot("old").chroot_base
    old_target.mkdir(parents=True)
    registry.upsert(name="old", distro="ubuntu", path=str(old_target), phase="finalize", installed=True)

    result = rename_chroot(config, registry, "old", "new")

    new_target = config.for_chroot("new").chroot_base
    assert result.new_name == "new"
    assert not old_target.exists()
    assert new_target.exists()
    record = registry.get("new")
    assert record is not None
    assert record["path"] == str(new_target)


def test_remove_chroot_refuses_registry_path_outside_chroot_root(tmp_path: Path) -> None:
    config, registry, logger = build_context(tmp_path)
    runner = Runner(dry_run=False)
    outside = tmp_path / "outside" / "ubuntu"
    outside.mkdir(parents=True)
    registry.upsert(name="ubuntu", distro="ubuntu", path=str(outside), phase="finalize", installed=True)

    with pytest.raises(RuntimeError, match="refusing to delete path outside chroot root"):
        remove_chroot(config, registry, runner, logger, "ubuntu")

    assert outside.exists()
    assert registry.get("ubuntu") is not None


def test_rename_chroot_requires_registry_record(tmp_path: Path) -> None:
    config, registry, _ = build_context(tmp_path)

    with pytest.raises(RuntimeError, match="no registry record for chroot: missing"):
        rename_chroot(config, registry, "missing", "new")
