
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

DEFAULT_MEDIA_MOUNTS = {
    "/sdcard/Documents": "home/mike/Documents",
    "/sdcard/Download": "home/mike/Downloads",
    "/sdcard/Pictures": "home/mike/Pictures",
    "/sdcard/Movies": "home/mike/Videos",
}
DEFAULT_DNS_SERVERS = ("8.8.8.8", "1.1.1.1")
ANDROID_STATE_ROOT = Path("/data/adb/chrootctl")
LEGACY_TERMUX_HOME = Path("/data/data/com.termux/files/home")


def is_android_runtime() -> bool:
    return bool(os.environ.get("ANDROID_ROOT")) or Path("/system/bin/app_process").exists()


def _legacy_config_path() -> Path:
    return LEGACY_TERMUX_HOME / ".config" / "chrootctl" / "config.json"


def _legacy_database_path() -> Path:
    return LEGACY_TERMUX_HOME / ".local" / "share" / "chrootctl" / "chroots.sqlite3"


def _legacy_snapshot_dir() -> Path:
    return LEGACY_TERMUX_HOME / ".local" / "share" / "chrootctl" / "snapshots"


def _default_state_root() -> Path:
    if is_android_runtime():
        return ANDROID_STATE_ROOT
    return Path.home() / ".local" / "share" / "chrootctl"


def _default_database_path() -> Path:
    return _default_state_root() / "chroots.sqlite3"


def _default_snapshot_dir() -> Path:
    return _default_state_root() / "snapshots"


def _default_config_path() -> Path:
    if is_android_runtime():
        return ANDROID_STATE_ROOT / "config.json"
    return Path.home() / ".config" / "chrootctl" / "config.json"


def _sqlite_chroot_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM chroots").fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def _copy_if_missing_or_empty(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _merge_tree_missing(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        dest = target / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)


def _migrate_android_runtime_layout() -> None:
    if not is_android_runtime():
        return

    state_root = ANDROID_STATE_ROOT
    state_root.mkdir(parents=True, exist_ok=True)

    legacy_config = _legacy_config_path()
    stable_config = _default_config_path()
    if not stable_config.exists() and legacy_config.exists():
        stable_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_config, stable_config)

    legacy_db = _legacy_database_path()
    stable_db = _default_database_path()
    if legacy_db.exists() and (_sqlite_chroot_count(stable_db) == 0) and (_sqlite_chroot_count(legacy_db) > 0):
        stable_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_db, stable_db)

    legacy_snapshots = _legacy_snapshot_dir()
    stable_snapshots = _default_snapshot_dir()
    if legacy_snapshots.exists():
        _merge_tree_missing(legacy_snapshots, stable_snapshots)


@dataclass(frozen=True, slots=True)
class BindMount:
    source: str
    target: str
    enabled: bool = True
    read_only: bool = False

def _default_media_mounts() -> tuple[BindMount, ...]:
    return tuple(BindMount(source, target) for source, target in DEFAULT_MEDIA_MOUNTS.items())

def _normalize_mounts(payload: Any) -> tuple[BindMount, ...]:
    mounts: list[BindMount] = []
    if payload is None:
        return ()
    if isinstance(payload, tuple) and all(isinstance(item, BindMount) for item in payload):
        return payload
    if isinstance(payload, dict):
        items = payload.items()
        for source, value in items:
            if isinstance(value, str):
                mounts.append(BindMount(source=str(source), target=value))
            elif isinstance(value, dict):
                mounts.append(
                    BindMount(
                        source=str(source),
                        target=str(value["target"]),
                        enabled=bool(value.get("enabled", True)),
                        read_only=bool(value.get("read_only", False)),
                    )
                )
            else:
                raise TypeError("mount definition must be a string target or object")
        return tuple(mounts)
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                raise TypeError("mount list entries must be objects")
            mounts.append(
                BindMount(
                    source=str(item["source"]),
                    target=str(item["target"]),
                    enabled=bool(item.get("enabled", True)),
                    read_only=bool(item.get("read_only", False)),
                )
            )
        return tuple(mounts)
    raise TypeError("mount configuration must be a mapping or list")

def _normalize_strings(payload: Any) -> tuple[str, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise TypeError("expected a list of strings")
    return tuple(str(item) for item in payload)


def _normalize_paths(payload: Any) -> tuple[Path, ...]:
    if payload is None:
        return ()
    if isinstance(payload, (str, Path)):
        return (Path(payload).expanduser(),)
    if not isinstance(payload, list):
        raise TypeError("expected a list of paths")
    return tuple(Path(item).expanduser() for item in payload)


def _normalize_android_runtime_path(path: Path, *, legacy: Path, stable: Path) -> Path:
    if is_android_runtime() and path == legacy:
        return stable
    return path

@dataclass(frozen=True, slots=True)
class ChrootConfig:
    chroot_root: Path = Path("/data/local/tmp")
    distro_name: str = "ubuntu"
    username: str = "mike"
    target_arch: str = "arm64"
    termux_home: Path = Path("/data/data/com.termux/files/home")
    termux_prefix: Path = Path("/data/data/com.termux/files/usr")
    log_file: Path = Path("/sdcard/.logs/chrootctl.log")
    database_path: Path = field(default_factory=_default_database_path)
    shell_path: str = "/usr/bin/zsh"
    mount_data_with_dev_suid: bool = True
    dev_shm_size: str = "256M"
    media_mounts: tuple[BindMount, ...] = field(default_factory=_default_media_mounts)
    extra_bind_mounts: tuple[BindMount, ...] = ()
    extra_packages: tuple[str, ...] = ()
    locale: str = "en_US.UTF-8"
    dns_servers: tuple[str, ...] = DEFAULT_DNS_SERVERS
    post_install_hooks: tuple[str, ...] = ()
    install_profile: str | None = None
    snapshot_dir: Path = field(default_factory=_default_snapshot_dir)
    snapshot_before_destructive: bool = False
    tool_manifest_dirs: tuple[Path, ...] = ()
    tool_script_dirs: tuple[Path, ...] = ()
    addon_manifest_dirs: tuple[Path, ...] = ()
    addon_script_dirs: tuple[Path, ...] = ()
    service_dirs: tuple[Path, ...] = field(default_factory=lambda: (_default_state_root() / "services",))
    service_state_dir: Path = field(default_factory=lambda: _default_state_root() / "run" / "services")
    service_log_dir: Path = field(default_factory=lambda: _default_state_root() / "logs" / "services")
    chroot_overrides: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_path", _normalize_android_runtime_path(self.database_path, legacy=_legacy_database_path(), stable=_default_database_path()))
        object.__setattr__(self, "snapshot_dir", _normalize_android_runtime_path(self.snapshot_dir, legacy=_legacy_snapshot_dir(), stable=_default_snapshot_dir()))
        object.__setattr__(self, "media_mounts", _normalize_mounts(self.media_mounts))
        object.__setattr__(self, "extra_bind_mounts", _normalize_mounts(self.extra_bind_mounts))
        object.__setattr__(self, "extra_packages", tuple(self.extra_packages))
        object.__setattr__(self, "dns_servers", tuple(self.dns_servers))
        object.__setattr__(self, "post_install_hooks", tuple(self.post_install_hooks))
        object.__setattr__(self, "tool_manifest_dirs", tuple(Path(item).expanduser() for item in self.tool_manifest_dirs))
        object.__setattr__(self, "tool_script_dirs", tuple(Path(item).expanduser() for item in self.tool_script_dirs))
        object.__setattr__(self, "addon_manifest_dirs", tuple(Path(item).expanduser() for item in self.addon_manifest_dirs))
        object.__setattr__(self, "addon_script_dirs", tuple(Path(item).expanduser() for item in self.addon_script_dirs))
        object.__setattr__(self, "service_dirs", tuple(Path(item).expanduser() for item in self.service_dirs))
        object.__setattr__(self, "service_state_dir", Path(self.service_state_dir).expanduser())
        object.__setattr__(self, "service_log_dir", Path(self.service_log_dir).expanduser())

    @property
    def chroot_base(self) -> Path:
        return self.chroot_root / self.distro_name

    @property
    def user_home_in_chroot(self) -> Path:
        return self.chroot_base / "home" / self.username

    @property
    def termux_home_in_chroot(self) -> Path:
        return self.chroot_base / "home" / "termux"

    @classmethod
    def default_config_path(cls) -> Path:
        return _default_config_path()

    @classmethod
    def _kwargs_from_payload(cls, payload: Mapping[str, Any], base: "ChrootConfig" | None = None) -> dict[str, Any]:
        current = base or cls()
        repositories = payload.get("repositories", {})
        if repositories is None:
            repositories = {}
        if not isinstance(repositories, Mapping):
            raise TypeError("repositories must be a mapping")
        return {
            "chroot_root": Path(payload.get("chroot_root", str(current.chroot_root))),
            "distro_name": payload.get("distro_name", current.distro_name),
            "username": payload.get("username", current.username),
            "target_arch": payload.get("target_arch", current.target_arch),
            "termux_home": Path(payload.get("termux_home", str(current.termux_home))),
            "termux_prefix": Path(payload.get("termux_prefix", str(current.termux_prefix))),
            "log_file": Path(payload.get("log_file", str(current.log_file))),
            "database_path": _normalize_android_runtime_path(Path(payload.get("database_path", str(current.database_path))), legacy=_legacy_database_path(), stable=_default_database_path()),
            "shell_path": payload.get("shell_path", current.shell_path),
            "mount_data_with_dev_suid": payload.get("mount_data_with_dev_suid", current.mount_data_with_dev_suid),
            "dev_shm_size": payload.get("dev_shm_size", current.dev_shm_size),
            "media_mounts": _normalize_mounts(payload.get("media_mounts", current.media_mounts)),
            "extra_bind_mounts": _normalize_mounts(payload.get("extra_bind_mounts", current.extra_bind_mounts)),
            "extra_packages": _normalize_strings(payload.get("extra_packages", list(current.extra_packages))),
            "locale": payload.get("locale", current.locale),
            "dns_servers": _normalize_strings(payload.get("dns_servers", list(current.dns_servers))) or current.dns_servers,
            "post_install_hooks": _normalize_strings(payload.get("post_install_hooks", list(current.post_install_hooks))),
            "install_profile": payload.get("install_profile", current.install_profile),
            "snapshot_dir": _normalize_android_runtime_path(Path(payload.get("snapshot_dir", str(current.snapshot_dir))), legacy=_legacy_snapshot_dir(), stable=_default_snapshot_dir()),
            "snapshot_before_destructive": payload.get("snapshot_before_destructive", current.snapshot_before_destructive),
            "tool_manifest_dirs": _normalize_paths(payload.get("tool_manifest_dirs", repositories.get("tool_manifests", list(current.tool_manifest_dirs)))),
            "tool_script_dirs": _normalize_paths(payload.get("tool_script_dirs", repositories.get("tool_scripts", list(current.tool_script_dirs)))),
            "addon_manifest_dirs": _normalize_paths(payload.get("addon_manifest_dirs", repositories.get("addon_manifests", list(current.addon_manifest_dirs)))),
            "addon_script_dirs": _normalize_paths(payload.get("addon_script_dirs", repositories.get("addon_scripts", list(current.addon_script_dirs)))),
            "service_dirs": _normalize_paths(payload.get("service_dirs", list(current.service_dirs))),
            "service_state_dir": Path(payload.get("service_state_dir", str(current.service_state_dir))).expanduser(),
            "service_log_dir": Path(payload.get("service_log_dir", str(current.service_log_dir))).expanduser(),
        }

    @classmethod
    def load(cls, path: Path | None = None) -> "ChrootConfig":
        if path is None:
            _migrate_android_runtime_layout()
        cfg_path = path or cls.default_config_path()
        if not cfg_path.exists():
            return cls()
        payload = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg = cls(**cls._kwargs_from_payload(payload))
        return cfg.with_overrides(chroot_overrides=dict(payload.get("chroot_overrides", {})))

    def resolved_shell(self, available_paths: Mapping[str, bool] | None = None) -> str:
        paths = available_paths or {}
        if paths.get(self.shell_path, False):
            return self.shell_path
        if paths.get("/bin/bash", False):
            return "/bin/bash"
        return self.shell_path

    def with_overrides(self, **kwargs: object) -> "ChrootConfig":
        return replace(self, **kwargs)

    def for_chroot(self, name: str) -> "ChrootConfig":
        cfg = self.with_overrides(distro_name=name)
        overrides = self.chroot_overrides.get(name)
        if not overrides:
            return cfg
        return cfg.with_overrides(**self._kwargs_from_payload(overrides, cfg))
