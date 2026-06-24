from __future__ import annotations

import subprocess
from pathlib import Path

from chrootctl.config import ChrootConfig
from chrootctl.parser import build_parser
from chrootctl.registry import ChrootRegistry
from chrootctl.services.chroots import export_chroot, import_chroot, inspect_chroot_archive
from chrootctl.services.context import ServiceContainer
from chrootctl.system import SystemRunner


class DummyLogger:
    def debug(self, *args, **kwargs): pass
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def exception(self, *args, **kwargs): pass


def _make_config(tmp_path: Path) -> ChrootConfig:
    return ChrootConfig(
        chroot_root=tmp_path / "chroots",
        database_path=tmp_path / "db.sqlite3",
        log_file=tmp_path / "chrootctl.log",
        distro_name="work",
        username="mike",
        target_arch="arm64",
    )


def test_install_parser_accepts_target_arch() -> None:
    parser = build_parser()
    args = parser.parse_args(["install", "ubuntu", "--phase", "extract", "--arch", "arm64", "--username", "mike"])
    assert args.arch == "arm64"


def test_export_import_roundtrip_tar_zst(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    logger = DummyLogger()
    runner = SystemRunner(logger=logger, dry_run=False)
    registry = ChrootRegistry(config.database_path)

    source_dir = config.chroot_base
    (source_dir / "etc").mkdir(parents=True)
    (source_dir / "etc" / "os-release").write_text("NAME=Ubuntu\n", encoding="utf-8")
    registry.upsert(
        name="work",
        distro="ubuntu",
        path=str(source_dir),
        arch="arm64",
        release_name="noble",
        version="24.04",
        phase="extract",
        installed=False,
        metadata={"origin": "test"},
    )

    archive = tmp_path / "work.tar.zst"
    exported = export_chroot(config, registry, runner, logger, "work", archive=archive)
    assert exported.archive == archive
    assert archive.exists()

    imported = import_chroot(
        config.with_overrides(distro_name="imported"),
        registry,
        runner,
        logger,
        archive=archive,
        name="imported",
    )
    assert imported.name == "imported"
    assert imported.arch == "arm64"
    assert (config.chroot_root / "imported" / "etc" / "os-release").exists()
    record = registry.get("imported")
    assert record is not None
    assert record["arch"] == "arm64"


def test_manage_source_install_editable_help() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["python3", str(repo_root / "manage_source.py"), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "build-magisk" in completed.stdout
    assert "install-editable" in completed.stdout
    assert "doctor-cross-arch" in completed.stdout


def test_transfer_parser_accepts_export_inspect_and_import(tmp_path: Path) -> None:
    parser = build_parser()
    export_args = parser.parse_args(["--name", "work", "transfer", "export", str(tmp_path / "work.tar.zst")])
    assert export_args.command == "transfer"
    assert export_args.transfer_command == "export"
    assert export_args.archive == tmp_path / "work.tar.zst"

    inspect_args = parser.parse_args(["transfer", "inspect", str(tmp_path / "work.tar.zst")])
    assert inspect_args.command == "transfer"
    assert inspect_args.transfer_command == "inspect"
    assert inspect_args.archive == tmp_path / "work.tar.zst"

    import_args = parser.parse_args(["transfer", "import", str(tmp_path / "work.tar.zst"), "--name", "phone-work"])
    assert import_args.command == "transfer"
    assert import_args.transfer_command == "import"
    assert import_args.import_name == "phone-work"


def test_export_writes_checksum_and_inspect_reads_metadata(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    logger = DummyLogger()
    runner = SystemRunner(logger=logger, dry_run=False)
    registry = ChrootRegistry(config.database_path)

    source_dir = config.chroot_base
    source_dir.mkdir(parents=True)
    (source_dir / "hello.txt").write_text("hi\n", encoding="utf-8")
    registry.upsert(
        name="work",
        distro="ubuntu",
        path=str(source_dir),
        arch="arm64",
        release_name="noble",
        version="24.04",
        phase="extract",
        installed=False,
        metadata={"profile": "minimal"},
    )
    archive = tmp_path / "work.tar.zst"
    exported = export_chroot(config, registry, runner, logger, "work", archive=archive)
    assert exported.checksum_path is not None
    assert exported.checksum_path.exists()
    inspection = inspect_chroot_archive(archive, registry=registry)
    assert inspection.size_bytes > 0
    assert inspection.checksum_verified is True
    assert inspection.target_exists is True
    assert inspection.release_name == "noble"


def test_import_conflict_rename_selects_next_available_name(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    logger = DummyLogger()
    runner = SystemRunner(logger=logger, dry_run=False)
    registry = ChrootRegistry(config.database_path)

    source_dir = config.chroot_base
    source_dir.mkdir(parents=True)
    (source_dir / "hello.txt").write_text("hi\n", encoding="utf-8")
    registry.upsert(
        name="work",
        distro="ubuntu",
        path=str(source_dir),
        arch="arm64",
        release_name="noble",
        version="24.04",
        phase="extract",
        installed=False,
        metadata={},
    )
    archive = tmp_path / "work.tar.zst"
    export_chroot(config, registry, runner, logger, "work", archive=archive)

    existing = config.chroot_root / "work-2"
    existing.mkdir(parents=True, exist_ok=True)

    imported = import_chroot(config, registry, runner, logger, archive=archive, name="work", conflict="rename")
    assert imported.name == "work-3"


def test_transfer_parser_accepts_conflict_strategy(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["transfer", "import", str(tmp_path / "work.tar.zst"), "--name", "phone-work", "--conflict", "overwrite"])
    assert args.conflict == "overwrite"


def test_transfer_import_parser_accepts_post_import(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args([
        "transfer",
        "import",
        str(tmp_path / "work.tar.zst"),
        "--name",
        "phone-work",
        "--post-import",
        "validate",
    ])
    assert args.post_import == "validate"


def test_export_import_roundtrip_encrypted_archive(tmp_path: Path) -> None:
    if not (Path("/usr/bin/openssl").exists() or Path("/bin/openssl").exists()):
        return
    config = _make_config(tmp_path)
    logger = DummyLogger()
    runner = SystemRunner(logger=logger, dry_run=False)
    registry = ChrootRegistry(config.database_path)

    source_dir = config.chroot_base
    (source_dir / "etc").mkdir(parents=True)
    (source_dir / "etc" / "os-release").write_text("NAME=Ubuntu\n", encoding="utf-8")
    registry.upsert(
        name="work",
        distro="ubuntu",
        path=str(source_dir),
        arch="arm64",
        release_name="noble",
        version="24.04",
        phase="extract",
        installed=False,
        metadata={"origin": "test"},
    )

    archive = tmp_path / "work.tar.zst"
    exported = export_chroot(config, registry, runner, logger, "work", archive=archive, password="secret")
    assert exported.encrypted is True
    assert exported.archive.name.endswith(".enc")

    imported = import_chroot(
        config.with_overrides(distro_name="secure"),
        registry,
        runner,
        logger,
        archive=exported.archive,
        name="secure",
        password="secret",
        post_import="validate",
    )
    assert imported.name == "secure"
    assert imported.encrypted is True
    assert imported.validation_ok is True


def test_audit_event_persistence_after_export_and_import(tmp_path: Path) -> None:
    if not (Path("/usr/bin/openssl").exists() or Path("/bin/openssl").exists()):
        return
    config = _make_config(tmp_path)
    logger = DummyLogger()
    runner = SystemRunner(logger=logger, dry_run=False)
    registry = ChrootRegistry(config.database_path)
    source_dir = config.chroot_base
    source_dir.mkdir(parents=True)
    (source_dir / "etc").mkdir(exist_ok=True)
    registry.upsert(
        name="work",
        distro="ubuntu",
        path=str(source_dir),
        arch="arm64",
        release_name="noble",
        version="24.04",
        phase="extract",
        installed=False,
        metadata={},
    )
    services = ServiceContainer(base_config=config, registry=registry, logger=logger, dry_run=False)
    exported = services.chroots().export("work", archive=tmp_path / "work.tar.zst", password="secret")
    imported = services.chroots().import_archive(exported.archive, name="audit-copy", password="secret", post_import="validate")
    events = services.audit().recent(limit=10)
    assert imported.name == "audit-copy"
    event_types = [event.event_type for event in events]
    assert "transfer.export" in event_types
    assert "transfer.import" in event_types
