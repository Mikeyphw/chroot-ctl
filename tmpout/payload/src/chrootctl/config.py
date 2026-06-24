from __future__ import annotations

import json
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

@dataclass(frozen=True, slots=True)
class ChrootConfig:
    chroot_root: Path = Path("/data/local/tmp")
    distro_name: str = "ubuntu"
    username: str = "mike"
    target_arch: str = "arm64"
    termux_home: Path = Path("/data/data/com.termux/files/home")
    termux_prefix: Path = Path("/data/data/com.termux/files/usr")
    log_file: Path = Path("/sdcard/.logs/chrootctl.log")
    database_path: Path = Path.home() / ".local" / "share" / "chrootctl" / "chroots.sqlite3"
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
    snapshot_dir: Path = Path.home() / ".local" / "share" / "chrootctl" / "snapshots"
    snapshot_before_destructive: bool = False
    tool_manifest_dirs: tuple[Path, ...] = ()
    tool_script_dirs: tuple[Path, ...] = ()
    addon_manifest_dirs: tuple[Path, ...] = ()
    addon_script_dirs: tuple[Path, ...] = ()
    chroot_overrides: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "media_mounts", _normalize_mounts(self.media_mounts))
        object.__setattr__(self, "extra_bind_mounts", _normalize_mounts(self.extra_bind_mounts))
        object.__setattr__(self, "extra_packages", tuple(self.extra_packages))
        object.__setattr__(self, "dns_servers", tuple(self.dns_servers))
        object.__setattr__(self, "post_install_hooks", tuple(self.post_install_hooks))
        object.__setattr__(self, "tool_manifest_dirs", tuple(Path(item).expanduser() for item in self.tool_manifest_dirs))
        object.__setattr__(self, "tool_script_dirs", tuple(Path(item).expanduser() for item in self.tool_script_dirs))
        object.__setattr__(self, "addon_manifest_dirs", tuple(Path(item).expanduser() for item in self.addon_manifest_dirs))
        object.__setattr__(self, "addon_script_dirs", tuple(Path(item).expanduser() for item in self.addon_script_dirs))

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
        return Path.home() / ".config" / "chrootctl" / "config.json"

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
            "database_path": Path(payload.get("database_path", str(current.database_path))),
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
            "snapshot_dir": Path(payload.get("snapshot_dir", str(current.snapshot_dir))),
            "snapshot_before_destructive": payload.get("snapshot_before_destructive", current.snapshot_before_destructive),
            "tool_manifest_dirs": _normalize_paths(payload.get("tool_manifest_dirs", repositories.get("tool_manifests", list(current.tool_manifest_dirs)))),
            "tool_script_dirs": _normalize_paths(payload.get("tool_script_dirs", repositories.get("tool_scripts", list(current.tool_script_dirs)))),
            "addon_manifest_dirs": _normalize_paths(payload.get("addon_manifest_dirs", repositories.get("addon_manifests", list(current.addon_manifest_dirs)))),
            "addon_script_dirs": _normalize_paths(payload.get("addon_script_dirs", repositories.get("addon_scripts", list(current.addon_script_dirs)))),
        }

    @classmethod
    def load(cls, path: Path | None = None) -> "ChrootConfig":
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
