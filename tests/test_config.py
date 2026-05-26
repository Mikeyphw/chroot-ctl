from pathlib import Path
import json

import chrootctl
import pytest
from chrootctl.config import ChrootConfig

def test_chroot_base_uses_name() -> None:
    cfg = ChrootConfig(distro_name="noble")
    assert cfg.chroot_root == Path("/data/local/tmp")
    assert cfg.chroot_base == Path("/data/local/tmp/noble")

def test_repo_imports_resolve_to_local_src() -> None:
    expected_root = Path(__file__).resolve().parents[1] / "src" / "chrootctl"
    assert Path(chrootctl.__file__).resolve().parent == expected_root

def test_load_uses_defaults_when_config_missing(tmp_path: Path) -> None:
    cfg = ChrootConfig.load(tmp_path / "missing.json")

    assert cfg == ChrootConfig()

def test_load_reads_custom_mount_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "mount_data_with_dev_suid": False,
                "media_mounts": {"/storage/shared": "mnt/shared"},
                "dev_shm_size": "64M",
            }
        ),
        encoding="utf-8",
    )

    cfg = ChrootConfig.load(config_path)

    assert cfg.mount_data_with_dev_suid is False
    assert len(cfg.media_mounts) == 1
    assert cfg.media_mounts[0].source == "/storage/shared"
    assert cfg.media_mounts[0].target == "mnt/shared"
    assert cfg.dev_shm_size == "64M"

def test_load_invalid_json_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{not-json}", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        ChrootConfig.load(config_path)


def test_load_supports_structured_mounts_and_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "media_mounts": {
                    "/storage/shared": {"target": "mnt/shared", "read_only": True},
                },
                "extra_bind_mounts": [
                    {"source": "/srv/cache", "target": "var/cache/shared", "enabled": True},
                ],
                "extra_packages": ["htop"],
                "locale": "pt_BR.UTF-8",
                "dns_servers": ["9.9.9.9"],
                "post_install_hooks": ["echo done"],
                "chroot_overrides": {
                    "work": {
                        "extra_packages": ["git-lfs"],
                        "install_profile": "dev",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = ChrootConfig.load(config_path)
    work_cfg = cfg.for_chroot("work")

    assert cfg.media_mounts[0].read_only is True
    assert cfg.extra_bind_mounts[0].target == "var/cache/shared"
    assert cfg.extra_packages == ("htop",)
    assert cfg.locale == "pt_BR.UTF-8"
    assert cfg.dns_servers == ("9.9.9.9",)
    assert cfg.post_install_hooks == ("echo done",)
    assert work_cfg.extra_packages == ("git-lfs",)
    assert work_cfg.install_profile == "dev"
