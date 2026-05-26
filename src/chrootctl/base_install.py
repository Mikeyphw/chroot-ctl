from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.error import URLError
from urllib.request import urlopen

from .config import ChrootConfig
from .controller import ChrootController
from .registry import ChrootRegistry
from .system import SystemRunner
from .user_sync import UserSyncManager, validate_username

InstallPhase = Literal["extract", "bootstrap", "desktop", "finalize"]
PHASES: tuple[InstallPhase, ...] = ("extract", "bootstrap", "desktop", "finalize")
URL_TIMEOUT_SECONDS = 15
PROFILE_DEFAULT_DESKTOP = {
    "minimal": "none",
    "dev": "none",
    "xfce4": "xfce4",
    "plasma": "plasma",
    "custom": "none",
}

class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.links.append(value)

@dataclass(slots=True)
class ReleaseRef:
    label: str
    url: str

class BaseInstaller:
    distro: str = ""
    arch: str = "arm64"

    def __init__(
        self,
        config: ChrootConfig,
        runner: SystemRunner,
        controller: ChrootController,
        registry: ChrootRegistry,
        user_sync: UserSyncManager,
        logger,
    ) -> None:
        self.config = config
        self.runner = runner
        self.controller = controller
        self.registry = registry
        self.user_sync = user_sync
        self.logger = logger

    def _fetch_text(self, url: str) -> str:
        try:
            with urlopen(url, timeout=URL_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except (URLError, OSError, TimeoutError) as exc:
            raise RuntimeError(f"failed to fetch {url}: {exc}") from exc

    def _validated_username(self, username: str) -> str:
        return validate_username(username)

    def _ensure_common_bootstrap_prereqs(self) -> None:
        self.controller.mount()
        self.controller.fix_tty()
        dns_lines = "\\n".join(f"nameserver {server}" for server in self.config.dns_servers)
        self._chroot_shell(f'printf "{dns_lines}\\n" > /etc/resolv.conf')
        self._chroot_shell('printf "127.0.0.1 localhost\\n::1 localhost\\n" > /etc/hosts')

    def _ensure_android_groups(self) -> None:
        self._require_chroot_commands("getent", "groupadd")
        for group_name, gid in (("aid_inet", 3003), ("aid_net_raw", 3004), ("aid_graphics", 1003)):
            self._chroot_shell(f"getent group {group_name} >/dev/null || groupadd -g {gid} {group_name}")

    def _ensure_common_user_groups(self) -> None:
        self._require_chroot_commands("getent", "groupadd")
        self._chroot_shell("getent group storage >/dev/null || groupadd storage")
        self._chroot_shell("getent group wheel >/dev/null || groupadd wheel")

    def _ensure_user(self, username: str, command: str) -> str:
        self._require_chroot_commands("id", "useradd")
        user = self._validated_username(username)
        self._chroot_shell(command.format(username=shlex.quote(user)))
        return user

    def _write_sudoers(self, username: str) -> None:
        user = self._validated_username(username)
        sudoers = self.config.chroot_base / "etc" / "sudoers.d" / user
        if not self.runner.dry_run:
            sudoers.parent.mkdir(parents=True, exist_ok=True)
            sudoers.write_text(f"{user} ALL=(ALL:ALL) ALL\n", encoding="utf-8")
            sudoers.chmod(0o440)

    def _download(self, url: str, target: Path) -> None:
        self.runner.run(
            [
                "curl",
                "--fail",
                "--location",
                "--connect-timeout",
                str(URL_TIMEOUT_SECONDS),
                "--max-time",
                "1800",
                "--retry",
                "3",
                "--progress-bar",
                url,
                "-o",
                str(target),
            ],
            capture_output=False,
        )

    def _verify_md5(self, file_path: Path, expected_md5: str) -> None:
        digest = hashlib.md5(usedforsecurity=False)
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_md5 = digest.hexdigest()
        if actual_md5 != expected_md5:
            raise RuntimeError(
                f"md5 mismatch for {file_path.name}: expected {expected_md5}, got {actual_md5}"
            )

    def phase_index(self, phase: str) -> int:
        return list(PHASES).index(phase) if phase in PHASES else 0

    def current_phase(self) -> InstallPhase:
        record = self.registry.get(self.config.distro_name)
        if record and record.get("phase") in PHASES:
            return record["phase"]
        return self.infer_phase_from_filesystem()

    def next_phase(self, phase: InstallPhase) -> InstallPhase | None:
        idx = PHASES.index(phase)
        return None if idx + 1 >= len(PHASES) else PHASES[idx + 1]

    def assert_phase_allowed(self, requested: InstallPhase, force_phase: bool) -> None:
        if force_phase:
            return
        current = self.current_phase()
        if self.phase_index(requested) > self.phase_index(current) + 1:
            raise RuntimeError(
                f"phase '{requested}' is gated because current phase is '{current}'. Use --force-phase to bypass."
            )

    def mark_phase(self, phase: InstallPhase, *, installed: bool = False, version: str | None = None, release_name: str | None = None, metadata: dict | None = None) -> None:
        record = self.registry.get(self.config.distro_name) or {}
        merged = dict(record.get("metadata", {}))
        if metadata:
            merged.update(metadata)
        self.registry.upsert(
            name=self.config.distro_name,
            distro=self.distro,
            path=str(self.config.chroot_base),
            phase=phase,
            installed=installed,
            arch=self.arch,
            release_name=release_name or record.get("release_name"),
            version=version or record.get("version"),
            metadata=merged,
        )

    def _chroot_shell(self, command: str) -> None:
        self.runner.run(
            ["busybox", "chroot", str(self.config.chroot_base), "/bin/bash", "-lc", command],
            chroot_env=True,
            capture_output=False,
        )

    def _chroot_shell_result(self, command: str) -> object:
        return self.runner.run(
            ["busybox", "chroot", str(self.config.chroot_base), "/bin/bash", "-lc", command],
            check=False,
            chroot_env=True,
        )

    def _require_chroot_commands(self, *commands: str) -> None:
        missing: list[str] = []
        for command in commands:
            result = self._chroot_shell_result(f"command -v {shlex.quote(command)} >/dev/null 2>&1")
            if result.returncode != 0:
                missing.append(command)
        if missing:
            raise RuntimeError(
                f"missing chroot command: {', '.join(missing)}; run install --phase bootstrap --repair"
            )

    def ready_for_bootstrap(self) -> bool:
        return True

    def _default_install_phase(self) -> InstallPhase:
        record = self.registry.get(self.config.distro_name)
        if record is None:
            return "extract"
        current = self.current_phase()
        if current == "extract" and not self.ready_for_bootstrap():
            return "extract"
        return self.next_phase(current) or "finalize"

    def _recover_phase_if_needed(self, requested: InstallPhase, *, force_phase: bool) -> InstallPhase:
        if self.phase_index(requested) >= self.phase_index("bootstrap") and not force_phase and not self.ready_for_bootstrap():
            return "extract"
        return requested

    def _selected_profile(self, profile: str | None) -> str:
        return profile or self.config.install_profile or "minimal"

    def _selected_desktop(self, desktop: str | None, profile: str | None) -> str:
        if desktop is not None:
            return desktop
        return PROFILE_DEFAULT_DESKTOP.get(self._selected_profile(profile), "none")

    def _extra_packages_for_profile(self, profile: str | None) -> tuple[str, ...]:
        return self.config.extra_packages

    def _run_post_install_hooks(self) -> None:
        for hook in self.config.post_install_hooks:
            self._chroot_shell(hook)

    def _create_snapshot(self, reason: str) -> str | None:
        if not self.config.snapshot_before_destructive:
            return None
        if not self.config.chroot_base.exists():
            return None
        snapshot_name = f"{self.config.distro_name}-{reason}.tar.gz"
        snapshot_path = self.config.snapshot_dir / snapshot_name
        if not self.runner.dry_run:
            self.config.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.runner.run(
            ["tar", "czf", str(snapshot_path), self.config.distro_name],
            cwd=self.config.chroot_root,
        )
        return str(snapshot_path)

    def list_versions(self) -> list[ReleaseRef]:
        raise NotImplementedError

    def infer_phase_from_filesystem(self) -> InstallPhase:
        raise NotImplementedError

    def run_phase_extract(self, *, version: str | None, release: str | None, force_phase: bool = False) -> dict[str, str]:
        raise NotImplementedError

    def run_phase_bootstrap(self, *, username: str, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        raise NotImplementedError

    def run_phase_desktop(self, *, desktop: str | None, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        raise NotImplementedError

    def upgrade(self) -> dict[str, str]:
        self.runner.require_root()
        snapshot = self._create_snapshot("upgrade")
        self.controller.mount()
        self.controller.fix_tty()
        self._run_upgrade()
        self._run_post_install_hooks()
        self.mark_phase(self.current_phase(), metadata={"last_upgrade": "true", "upgrade_snapshot": snapshot or ""})
        return {"status": "upgraded", "snapshot": snapshot or ""}

    def _run_upgrade(self) -> None:
        raise NotImplementedError

    def run_phase_finalize(self, *, username: str, force_phase: bool = False) -> dict[str, str]:
        self.assert_phase_allowed("finalize", force_phase)
        snapshot = self._create_snapshot("finalize")
        self.user_sync.sync_id(username=username, fix_ownership=True)
        self._run_post_install_hooks()
        self.mark_phase("finalize", installed=True, metadata={"uid_sync": True, "finalize_snapshot": snapshot or ""})
        return {"phase": "finalize", "installed": "true", "uid_sync": "true", "snapshot": snapshot or ""}

    def install(self, *, phase: InstallPhase | None, username: str, desktop: str | None, version: str | None, release: str | None, force_phase: bool, auto: bool, resume: bool = False, repair: bool = False, profile: str | None = None) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        selected_profile = self._selected_profile(profile)
        selected_desktop = self._selected_desktop(desktop, selected_profile)
        if repair:
            current = self.current_phase()
            current = self._recover_phase_if_needed(current, force_phase=force_phase)
            if current == "extract":
                return [self.run_phase_extract(version=version, release=release, force_phase=True)]
            if current == "bootstrap":
                return [self.run_phase_bootstrap(username=username, profile=selected_profile, force_phase=True)]
            if current == "desktop":
                return [self.run_phase_desktop(desktop=selected_desktop, profile=selected_profile, force_phase=True)]
            return [self.run_phase_finalize(username=username, force_phase=True)]
        if auto or resume or phase is None:
            record = self.registry.get(self.config.distro_name)
            if record and record.get("installed"):
                return [{"phase": "finalize", "installed": "true", "status": "already_complete"}]
            start_phase = phase or self._default_install_phase()
            start_phase = self._recover_phase_if_needed(start_phase, force_phase=force_phase)
            for item in PHASES[PHASES.index(start_phase):]:
                if item == "extract":
                    results.append(self.run_phase_extract(version=version, release=release, force_phase=force_phase))
                elif item == "bootstrap":
                    results.append(self.run_phase_bootstrap(username=username, profile=selected_profile, force_phase=force_phase))
                elif item == "desktop":
                    results.append(self.run_phase_desktop(desktop=selected_desktop, profile=selected_profile, force_phase=force_phase))
                elif item == "finalize":
                    results.append(self.run_phase_finalize(username=username, force_phase=force_phase))
            return results

        requested = phase or self._default_install_phase()
        requested = self._recover_phase_if_needed(requested, force_phase=force_phase)
        if requested == "extract":
            return [self.run_phase_extract(version=version, release=release, force_phase=force_phase)]
        if requested == "bootstrap":
            return [self.run_phase_bootstrap(username=username, profile=selected_profile, force_phase=force_phase)]
        if requested == "desktop":
            return [self.run_phase_desktop(desktop=selected_desktop, profile=selected_profile, force_phase=force_phase)]
        if requested == "finalize":
            return [self.run_phase_finalize(username=username, force_phase=force_phase)]
        raise ValueError(f"unsupported phase: {requested}")
