from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.request import urlopen

from .config import ChrootConfig
from .controller import ChrootController
from .registry import ChrootRegistry
from .system import SystemRunner
from .user_sync import UserSyncManager

InstallPhase = Literal["extract", "bootstrap", "desktop", "finalize"]
PHASES: tuple[InstallPhase, ...] = ("extract", "bootstrap", "desktop", "finalize")

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
            capture_output=False,
        )

    def list_versions(self) -> list[ReleaseRef]:
        raise NotImplementedError

    def infer_phase_from_filesystem(self) -> InstallPhase:
        raise NotImplementedError

    def run_phase_extract(self, *, version: str | None, release: str | None, force_phase: bool = False) -> dict[str, str]:
        raise NotImplementedError

    def run_phase_bootstrap(self, *, username: str, force_phase: bool = False) -> dict[str, str]:
        raise NotImplementedError

    def run_phase_desktop(self, *, desktop: str, force_phase: bool = False) -> dict[str, str]:
        raise NotImplementedError

    def run_phase_finalize(self, *, username: str, force_phase: bool = False) -> dict[str, str]:
        self.assert_phase_allowed("finalize", force_phase)
        self.user_sync.sync_id(username=username, fix_ownership=True)
        self.mark_phase("finalize", installed=True, metadata={"uid_sync": True})
        return {"phase": "finalize", "installed": "true", "uid_sync": "true"}

    def install(self, *, phase: InstallPhase | None, username: str, desktop: str, version: str | None, release: str | None, force_phase: bool, auto: bool) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        if auto:
            record = self.registry.get(self.config.distro_name)
            if record and record.get("installed"):
                return [{"phase": "finalize", "installed": "true", "status": "already_complete"}]
            start_phase = "extract" if record is None else (self.next_phase(self.current_phase()) or "finalize")
            for item in PHASES[PHASES.index(start_phase):]:
                if item == "extract":
                    results.append(self.run_phase_extract(version=version, release=release, force_phase=force_phase))
                elif item == "bootstrap":
                    results.append(self.run_phase_bootstrap(username=username, force_phase=force_phase))
                elif item == "desktop":
                    results.append(self.run_phase_desktop(desktop=desktop, force_phase=force_phase))
                elif item == "finalize":
                    results.append(self.run_phase_finalize(username=username, force_phase=force_phase))
            return results

        requested = phase or self.current_phase()
        if requested == "extract":
            return [self.run_phase_extract(version=version, release=release, force_phase=force_phase)]
        if requested == "bootstrap":
            return [self.run_phase_bootstrap(username=username, force_phase=force_phase)]
        if requested == "desktop":
            return [self.run_phase_desktop(desktop=desktop, force_phase=force_phase)]
        if requested == "finalize":
            return [self.run_phase_finalize(username=username, force_phase=force_phase)]
        raise ValueError(f"unsupported phase: {requested}")
