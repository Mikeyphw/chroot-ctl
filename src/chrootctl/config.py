from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

DEFAULT_MEDIA_MOUNTS = {
    "/sdcard/Documents": "home/mike/Documents",
    "/sdcard/Download": "home/mike/Downloads",
    "/sdcard/Pictures": "home/mike/Pictures",
    "/sdcard/Movies": "home/mike/Videos",
}

@dataclass(frozen=True, slots=True)
class ChrootConfig:
    chroot_root: Path = Path("/data/local/chroot")
    distro_name: str = "ubuntu"
    username: str = "mike"
    termux_home: Path = Path("/data/data/com.termux/files/home")
    termux_prefix: Path = Path("/data/data/com.termux/files/usr")
    log_file: Path = Path("/sdcard/.logs/chrootctl.log")
    database_path: Path = Path.home() / ".local" / "share" / "chrootctl" / "chroots.sqlite3"
    shell_path: str = "/usr/bin/zsh"
    mount_data_with_dev_suid: bool = True
    dev_shm_size: str = "256M"
    media_mounts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MEDIA_MOUNTS))

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
    def load(cls, path: Path | None = None) -> "ChrootConfig":
        cfg_path = path or cls.default_config_path()
        if not cfg_path.exists():
            return cls()
        payload = json.loads(cfg_path.read_text(encoding="utf-8"))
        media_mounts = payload.get("media_mounts", DEFAULT_MEDIA_MOUNTS)
        return cls(
            chroot_root=Path(payload.get("chroot_root", str(cls().chroot_root))),
            distro_name=payload.get("distro_name", cls().distro_name),
            username=payload.get("username", cls().username),
            termux_home=Path(payload.get("termux_home", str(cls().termux_home))),
            termux_prefix=Path(payload.get("termux_prefix", str(cls().termux_prefix))),
            log_file=Path(payload.get("log_file", str(cls().log_file))),
            database_path=Path(payload.get("database_path", str(cls().database_path))),
            shell_path=payload.get("shell_path", cls().shell_path),
            mount_data_with_dev_suid=payload.get("mount_data_with_dev_suid", cls().mount_data_with_dev_suid),
            dev_shm_size=payload.get("dev_shm_size", cls().dev_shm_size),
            media_mounts=dict(media_mounts),
        )

    def resolved_shell(self, available_paths: Mapping[str, bool] | None = None) -> str:
        paths = available_paths or {}
        if paths.get(self.shell_path, False):
            return self.shell_path
        if paths.get("/bin/bash", False):
            return "/bin/bash"
        return self.shell_path

    def with_overrides(self, **kwargs: object) -> "ChrootConfig":
        return replace(self, **kwargs)
