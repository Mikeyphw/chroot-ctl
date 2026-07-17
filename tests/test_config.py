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


def test_non_android_defaults_stay_home_scoped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("chrootctl.config.is_android_runtime", lambda: False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    cfg = ChrootConfig()

    assert cfg.database_path == tmp_path / ".local" / "share" / "chrootctl" / "chroots.sqlite3"
    assert cfg.snapshot_dir == tmp_path / ".local" / "share" / "chrootctl" / "snapshots"
    assert ChrootConfig.default_config_path() == tmp_path / ".config" / "chrootctl" / "config.json"


def test_android_defaults_use_stable_adb_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chrootctl.config.is_android_runtime", lambda: True)

    cfg = ChrootConfig()

    assert cfg.database_path == Path("/data/adb/chrootctl/chroots.sqlite3")
    assert cfg.snapshot_dir == Path("/data/adb/chrootctl/snapshots")
    assert ChrootConfig.default_config_path() == Path("/data/adb/chrootctl/config.json")


def test_android_load_migrates_termux_home_registry_and_snapshots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import chrootctl.config as config_mod

    stable_root = tmp_path / "adb" / "chrootctl"
    legacy_home = tmp_path / "termux-home"
    legacy_config = legacy_home / ".config" / "chrootctl" / "config.json"
    legacy_db = legacy_home / ".local" / "share" / "chrootctl" / "chroots.sqlite3"
    legacy_snapshots = legacy_home / ".local" / "share" / "chrootctl" / "snapshots"
    legacy_config.parent.mkdir(parents=True, exist_ok=True)
    legacy_db.parent.mkdir(parents=True, exist_ok=True)
    legacy_snapshots.mkdir(parents=True, exist_ok=True)

    legacy_config.write_text(
        json.dumps(
            {
                "database_path": str(legacy_db),
                "snapshot_dir": str(legacy_snapshots),
                "username": "mike",
            }
        ),
        encoding="utf-8",
    )

    import sqlite3

    with sqlite3.connect(legacy_db) as conn:
        conn.execute(
            "CREATE TABLE chroots (name TEXT PRIMARY KEY, distro TEXT NOT NULL, path TEXT NOT NULL, arch TEXT, release_name TEXT, version TEXT, phase TEXT NOT NULL, installed INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO chroots (name, distro, path, phase, installed, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("androidos", "ubuntu", "/data/local/tmp/androidos", "ready", 1, "{}"),
        )
        conn.commit()

    (legacy_snapshots / "snap1.tar.zst").write_text("snapshot", encoding="utf-8")

    monkeypatch.setattr(config_mod, "is_android_runtime", lambda: True)
    monkeypatch.setattr(config_mod, "ANDROID_STATE_ROOT", stable_root)
    monkeypatch.setattr(config_mod, "LEGACY_TERMUX_HOME", legacy_home)

    cfg = ChrootConfig.load()

    assert cfg.database_path == stable_root / "chroots.sqlite3"
    assert cfg.snapshot_dir == stable_root / "snapshots"
    assert ChrootConfig.default_config_path() == stable_root / "config.json"
    assert (stable_root / "config.json").exists()
    assert (stable_root / "chroots.sqlite3").exists()
    assert (stable_root / "snapshots" / "snap1.tar.zst").exists()

    with sqlite3.connect(stable_root / "chroots.sqlite3") as conn:
        names = [row[0] for row in conn.execute("SELECT name FROM chroots")]
    assert names == ["androidos"]
