
from pathlib import Path

from chrootctl.config import ChrootConfig
from chrootctl.registry import ChrootRegistry
from chrootctl.services.context import ServiceContainer


def _services(tmp_path: Path) -> ServiceContainer:
    root = tmp_path / "chroots"
    config = ChrootConfig(
        distro_name="ubuntu",
        chroot_root=root,
        log_file=tmp_path / "logs" / "chrootctl.log",
        database_path=tmp_path / "state" / "registry.db",
    )
    return ServiceContainer(
        base_config=config,
        registry=ChrootRegistry(config.database_path),
        logger=None,
    )


def test_registry_repair_preview_and_apply(tmp_path: Path):
    services = _services(tmp_path)
    orphan = services.base_config.chroot_root / "orphan"
    orphan.mkdir(parents=True)
    services.registry.upsert(
        name="broken",
        distro="ubuntu",
        path=str(services.base_config.chroot_root / "missing"),
        phase="registered",
        installed=False,
    )
    preview = services.repair().preview_registry_repair()
    assert "orphan" in preview.missing_records
    assert "broken" in preview.missing_paths
    applied = services.repair().apply_registry_repair()
    assert "orphan" in applied.repaired_records
    assert "broken" in applied.removed_records
    assert services.registry.get("orphan") is not None
    assert services.registry.get("broken") is None
