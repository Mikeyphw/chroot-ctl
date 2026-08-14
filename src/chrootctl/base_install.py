from __future__ import annotations

import os
import re
import shlex
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.error import URLError
from urllib.request import urlopen

from .config import ChrootConfig
from .controller import ChrootController
from .models import (
    InstallAlreadyCompleteResult,
    InstallFinalizeResult,
    InstallerResult,
    UpgradeResult,
)
from .registry import ChrootRegistry
from .install_integrity import InstallFetchError
from .system import SystemRunner, qemu_user_binary_names
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

    def to_display_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "url": self.url,
        }


class BaseInstaller:
    distro: str = ""
    default_arch: str = "arm64"

    @property
    def arch(self) -> str:
        return getattr(self.config, "target_arch", self.default_arch)

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
        self._mirror_selection = "auto"
        self._mirror_candidates: tuple[dict[str, str], ...] = ()
        self._mirror_base_url: str | None = None

    def configure_mirror_plan(
        self,
        *,
        selection: str,
        base_url: str | None,
        candidates: list[dict[str, str]] | tuple[dict[str, str], ...],
    ) -> None:
        self._mirror_selection = selection or "auto"
        self._mirror_base_url = (base_url or "").rstrip("/") or None
        cleaned: list[dict[str, str]] = []
        for item in candidates:
            candidate_id = str(item.get("id", "")).strip()
            candidate_url = str(item.get("url", "")).strip().rstrip("/")
            if not candidate_id or not candidate_url:
                continue
            cleaned.append({"id": candidate_id, "url": candidate_url})
        self._mirror_candidates = tuple(cleaned)

    def current_mirror_selection(self) -> str:
        return self._mirror_selection

    def _mirror_label(self, url: str) -> str:
        for item in self._mirror_candidates:
            if item["url"] == url.rstrip("/"):
                return item["id"]
        return url

    def _mirror_variants(self, url: str) -> list[tuple[str, str]]:
        selected = url.rstrip("/")
        # Package mirrors are not assumed to mirror arbitrary rootfs/release URLs.
        # If the URL is outside the configured mirror namespace, fetch it once and
        # rely on that endpoint's own redirect/geo policy.
        if not self._mirror_base_url or not selected.startswith(self._mirror_base_url.rstrip("/")):
            return [(self._mirror_label(selected), selected)]
        selected = self._mirror_base_url.rstrip("/")
        variants: list[tuple[str, str]] = [(self._mirror_label(selected), selected)]
        seen = {selected}
        for item in self._mirror_candidates:
            candidate_url = item["url"]
            if candidate_url in seen:
                continue
            variants.append((item["id"], candidate_url))
            seen.add(candidate_url)
        return variants

    def _rewrite_url_to_mirror(self, url: str, mirror_url: str) -> str:
        if not self._mirror_base_url:
            return url
        normalized_base = self._mirror_base_url.rstrip("/")
        if not url.startswith(normalized_base):
            return url
        return f"{mirror_url.rstrip('/')}{url[len(normalized_base):]}"

    def _fetch_text_with_mirror_fallback(self, url: str) -> str:
        last_error: Exception | None = None
        for mirror_id, mirror_url in self._mirror_variants(url):
            candidate = self._rewrite_url_to_mirror(url, mirror_url)
            try:
                self.logger.info("fetching %s via mirror %s", candidate, mirror_id)
                return self._fetch_text(candidate)
            except InstallFetchError as exc:
                last_error = exc
                self.logger.warning("failed to fetch %s via mirror %s: %s", candidate, mirror_id, exc)
        if last_error is not None:
            raise RuntimeError(f"failed to fetch {url} across mirrors: {last_error}") from last_error
        return self._fetch_text(url)

    def _download_with_mirror_fallback(self, url: str, target: Path) -> str:
        last_error: Exception | None = None
        for mirror_id, mirror_url in self._mirror_variants(url):
            candidate = self._rewrite_url_to_mirror(url, mirror_url)
            try:
                self.logger.info("downloading %s via mirror %s", candidate, mirror_id)
                self._download(candidate, target)
                return candidate
            except InstallFetchError as exc:
                last_error = exc
                self.logger.warning("failed to download %s via mirror %s: %s", candidate, mirror_id, exc)
        if last_error is not None:
            raise RuntimeError(f"failed to download {url} across mirrors: {last_error}") from last_error
        self._download(url, target)
        return url

    def _requires_foreign_arch_emulation(self) -> bool:
        host_arch_fn = getattr(self.runner, "host_arch", None)
        host_arch = host_arch_fn() if callable(host_arch_fn) else self.arch
        return host_arch not in {"", self.arch}

    def _ensure_chroot_execution_supported(self) -> None:
        if not self._requires_foreign_arch_emulation():
            return
        can_execute_fn = getattr(self.runner, "can_execute_foreign_arch", None)
        if callable(can_execute_fn) and can_execute_fn(self.arch):
            self.logger.info("detected foreign-arch execution support for %s via qemu/binfmt", self.arch)
            return
        host_arch_fn = getattr(self.runner, "host_arch", None)
        host_arch = host_arch_fn() if callable(host_arch_fn) else "unknown"
        qemu_binary = qemu_user_binary_names(self.arch)[0]
        raise RuntimeError(
            f"target arch {self.arch} differs from host arch {host_arch}; "
            f"extract is supported, but bootstrap/desktop/finalize/upgrade require user-mode emulation such as {qemu_binary}. "
            f"Install {qemu_binary} and enable binfmt_misc, or create the rootfs with 'chrootctl install ... --phase extract --arch {self.arch}', "
            f"then export/import it to your {self.arch} phone."
        )

    def _fetch_text(self, url: str) -> str:
        try:
            with urlopen(url, timeout=URL_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except (URLError, OSError, TimeoutError) as exc:
            raise InstallFetchError(f"failed to fetch {url}: {exc}") from exc

    def _validated_username(self, username: str) -> str:
        return validate_username(username)

    def _ensure_common_bootstrap_prereqs(self) -> None:
        self.controller.mount()
        self.controller.fix_tty()
        dns_lines = "\\n".join(f"nameserver {server}" for server in self.config.dns_servers) + "\\n"
        self._chroot_shell(f"printf %s {shlex.quote(dns_lines)} > /etc/resolv.conf")
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
        sudoers_dir = self.config.chroot_base / "etc" / "sudoers.d"
        sudoers = sudoers_dir / user
        if self.runner.dry_run:
            return
        sudoers_dir.mkdir(parents=True, exist_ok=True)
        if sudoers_dir.is_symlink() or not sudoers_dir.is_dir():
            raise RuntimeError(f"unsafe sudoers directory: {sudoers_dir}")
        if sudoers.is_symlink():
            raise RuntimeError(f"refusing sudoers symlink: {sudoers}")
        fd, raw = tempfile.mkstemp(prefix=f".{user}.", dir=sudoers_dir)
        temp = Path(raw)
        try:
            os.fchmod(fd, 0o440)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{user} ALL=(ALL:ALL) ALL\n")
                handle.flush(); os.fsync(handle.fileno())
            rel = "/etc/sudoers.d/" + temp.name
            result = self._chroot_shell_result(f"visudo -cf {shlex.quote(rel)}")
            if result.returncode != 0:
                detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part).strip()
                raise RuntimeError(detail or f"visudo rejected sudoers rule for {user}")
            os.replace(temp, sudoers)
            sudoers.chmod(0o440)
        finally:
            temp.unlink(missing_ok=True)

    def _download(self, url: str, target: Path) -> None:
        try:
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
        except Exception as exc:
            raise InstallFetchError(f"failed to download {url}: {exc}") from exc

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

    def mark_phase(
        self,
        phase: InstallPhase,
        *,
        installed: bool = False,
        version: str | None = None,
        release_name: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if self.runner.dry_run:
            return
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
        selected_profile = self._selected_profile(profile)
        requested_desktop = (desktop or "").strip() or "auto"
        if selected_profile == "minimal":
            if requested_desktop not in {"auto", "none"}:
                raise ValueError("minimal profile does not allow desktop installation; choose profile xfce4/plasma or desktop none")
            return "none"
        if requested_desktop == "auto":
            return PROFILE_DEFAULT_DESKTOP.get(selected_profile, "none")
        return requested_desktop

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

    def _new_install_work_dir(self, label: str) -> Path:
        path = self.config.chroot_base.parent / f".{self.config.distro_name}.{label}-{uuid.uuid4().hex}"
        if not self.runner.dry_run:
            path.mkdir(parents=True, mode=0o700)
        return path

    def _assert_install_target_unmounted(self) -> None:
        target = str(self.config.chroot_base.resolve(strict=False))
        for _source, destination in self.runner.mount_table():
            resolved = str(Path(destination).resolve(strict=False))
            if resolved == target or resolved.startswith(target + os.sep):
                raise RuntimeError(f"refusing rootfs replacement while target is mounted: {destination}")

    def _promote_staged_rootfs(self, staged_root: Path) -> None:
        if self.runner.dry_run:
            return
        target = self.config.chroot_base
        if staged_root.parent != target.parent:
            raise RuntimeError("install staging must share the target filesystem")
        self._assert_install_target_unmounted()
        backup = target.parent / f".{target.name}.preinstall-{uuid.uuid4().hex}"
        had_existing = target.exists()
        mutation_id = self.registry.begin_fs_mutation(
            kind="install.extract", target=self.config.distro_name, source_path=str(staged_root),
            destination_path=str(target), detail={"backup": str(backup), "had_existing": had_existing},
        )
        moved_old = False
        promoted = False
        try:
            if had_existing:
                os.replace(target, backup)
                moved_old = True
                self._best_effort_install_mutation_state(mutation_id, "staged")
            os.replace(staged_root, target)
            promoted = True
            # The registry marker and promoted tree form the authoritative commit.
            # If the marker cannot be persisted while the backup is still present,
            # restore the old generation instead of leaving ambiguous state.
            self._mark_install_fs_commit(mutation_id)
        except Exception:
            if promoted and target.exists():
                os.replace(target, staged_root)
            if moved_old and backup.exists() and not target.exists():
                os.replace(backup, target)
            self._best_effort_install_mutation_state(mutation_id, "failed")
            raise
        self._best_effort_install_mutation_state(mutation_id, "committed")
        if backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError as exc:
                self._best_effort_install_mutation_state(
                    mutation_id, "committed", detail={"cleanup_error": str(exc)[:1000], "backup": str(backup)}
                )
                return
        self._best_effort_install_mutation_state(mutation_id, "complete")

    def _mark_install_fs_commit(self, mutation_id: str) -> None:
        record = self.registry.get(self.config.distro_name) or {}
        metadata = dict(record.get("metadata", {})) if isinstance(record.get("metadata", {}), dict) else {}
        metadata["_chrootctl_install_mutation_id"] = mutation_id
        self.registry.upsert(
            name=self.config.distro_name, distro=self.distro, path=str(self.config.chroot_base),
            phase="extract", installed=False,
            arch=self.arch, release_name=record.get("release_name"), version=record.get("version"), metadata=metadata,
        )

    def _best_effort_install_mutation_state(self, mutation_id: str, state: str, *, detail: dict[str, Any] | None = None) -> None:
        try:
            self.registry.update_fs_mutation(mutation_id, state, detail=detail or {})
        except Exception as exc:
            try:
                self.logger.warning("failed to update install filesystem mutation %s to %s: %s", mutation_id, state, exc)
            except Exception:
                pass

    def _install_transaction(self) -> dict[str, Any]:
        record = self.registry.get(self.config.distro_name) or {}
        metadata = record.get("metadata", {})
        value = metadata.get("install_transaction") if isinstance(metadata, dict) else None
        if isinstance(value, dict) and isinstance(value.get("steps"), dict):
            version = int(value.get("version", 1)) if str(value.get("version", 1)).isdigit() else 1
            return {"version": max(version, 2), "steps": dict(value["steps"])}
        return {"version": 2, "steps": {}}

    def _record_install_step(self, step: str, state: str, *, error: str | None = None) -> None:
        if self.runner.dry_run:
            return
        record = self.registry.get(self.config.distro_name) or {}
        metadata = dict(record.get("metadata", {})) if isinstance(record.get("metadata", {}), dict) else {}
        transaction = self._install_transaction()
        steps = dict(transaction.get("steps", {}))
        detail: dict[str, Any] = {"state": state, "updated_at": time.time()}
        context_key = str(getattr(self, "_install_context_key", "") or "")
        if context_key:
            detail["context"] = context_key
        if error:
            detail["error"] = error[:1000]
        steps[step] = detail
        metadata["install_transaction"] = {"version": 2, "steps": steps}
        self.registry.upsert(
            name=self.config.distro_name, distro=self.distro, path=str(self.config.chroot_base),
            phase=str(record.get("phase") or "extract"), installed=bool(record.get("installed", False)),
            arch=self.arch, release_name=record.get("release_name"), version=record.get("version"), metadata=metadata,
        )

    def _run_tracked_phase(self, phase: InstallPhase, callback):
        self._record_install_step(phase, "running")
        try:
            result = callback()
        except Exception as exc:
            self._record_install_step(phase, "failed", error=str(exc))
            raise
        self._record_install_step(phase, "completed")
        return result

    def _run_install_substep(self, phase: InstallPhase, name: str, callback, *, resumable: bool = True):
        step = f"{phase}.{name}"
        existing = self._install_transaction().get("steps", {}).get(step, {})
        resume_mode = bool(getattr(self, "_install_resume_mode", False))
        context_key = str(getattr(self, "_install_context_key", "") or "")
        if resumable and resume_mode and isinstance(existing, dict) and existing.get("state") == "completed":
            existing_context = str(existing.get("context", "") or "")
            if not existing_context or existing_context != context_key:
                raise RuntimeError(f"cannot resume {step}: install request context changed; start a new explicit install/repair plan")
            return None
        self._record_install_step(step, "running")
        try:
            result = callback()
        except Exception as exc:
            self._record_install_step(step, "failed", error=str(exc))
            raise
        self._record_install_step(step, "completed")
        return result

    def _resume_start_phase(self, *, repair: bool) -> InstallPhase:
        steps = self._install_transaction().get("steps", {})
        if isinstance(steps, dict) and steps:
            if repair:
                for phase in PHASES:
                    value = steps.get(phase, {})
                    if isinstance(value, dict) and value.get("state") in {"failed", "running"}:
                        return phase
            for phase in PHASES:
                value = steps.get(phase, {})
                if not isinstance(value, dict) or value.get("state") != "completed":
                    return phase
            return "finalize"
        return self._recover_phase_if_needed(self.current_phase(), force_phase=False)

    def list_versions(self) -> list[ReleaseRef]:
        raise NotImplementedError

    def infer_phase_from_filesystem(self) -> InstallPhase:
        raise NotImplementedError

    def run_phase_extract(
        self,
        *,
        version: str | None,
        release: str | None,
        force_phase: bool = False,
    ) -> InstallerResult:
        raise NotImplementedError

    def run_phase_bootstrap(
        self,
        *,
        username: str,
        profile: str | None = None,
        force_phase: bool = False,
    ) -> InstallerResult:
        raise NotImplementedError

    def run_phase_desktop(
        self,
        *,
        desktop: str | None,
        profile: str | None = None,
        force_phase: bool = False,
    ) -> InstallerResult:
        raise NotImplementedError

    def upgrade(self) -> UpgradeResult:
        self.runner.require_root()
        self._ensure_chroot_execution_supported()
        snapshot = self._create_snapshot("upgrade")
        self.controller.mount()
        self.controller.fix_tty()
        self._run_upgrade()
        self._run_post_install_hooks()
        self.mark_phase(self.current_phase(), metadata={"last_upgrade": "true", "upgrade_snapshot": snapshot or ""})
        return UpgradeResult(status="upgraded", snapshot=snapshot or "")

    def _run_upgrade(self) -> None:
        raise NotImplementedError

    def run_phase_finalize(self, *, username: str, force_phase: bool = False) -> InstallFinalizeResult:
        self._ensure_chroot_execution_supported()
        self.assert_phase_allowed("finalize", force_phase)
        snapshot = self._create_snapshot("finalize")
        self._run_install_substep("finalize", "uid-sync", lambda: self.user_sync.sync_id(username=username, fix_ownership=True))
        self._run_install_substep("finalize", "post-install-hooks", self._run_post_install_hooks)
        self.mark_phase("finalize", installed=True, metadata={"uid_sync": True, "finalize_snapshot": snapshot or ""})
        return InstallFinalizeResult(installed=True, uid_sync=True, snapshot=snapshot or "")

    def install(
        self,
        *,
        phase: InstallPhase | None,
        username: str,
        desktop: str | None,
        version: str | None,
        release: str | None,
        force_phase: bool,
        auto: bool,
        resume: bool = False,
        repair: bool = False,
        profile: str | None = None,
    ) -> list[InstallerResult]:
        results: list[InstallerResult] = []
        self._install_resume_mode = bool(resume or repair)
        selected_profile = self._selected_profile(profile)
        selected_desktop = self._selected_desktop(desktop, selected_profile)
        self._install_context_key = "|".join((
            self.distro, self.arch, self.config.distro_name, username, selected_profile, selected_desktop,
            version or "", release or "",
        ))
        record = self.registry.get(self.config.distro_name)
        if not repair and (auto or resume or phase is None) and record and record.get("installed"):
            return [InstallAlreadyCompleteResult()]

        def run_one(item: InstallPhase):
            if item == "extract":
                return self._run_tracked_phase(item, lambda: self.run_phase_extract(version=version, release=release, force_phase=force_phase or repair))
            if item == "bootstrap":
                return self._run_tracked_phase(item, lambda: self.run_phase_bootstrap(username=username, profile=selected_profile, force_phase=force_phase or repair))
            if item == "desktop":
                return self._run_tracked_phase(item, lambda: self.run_phase_desktop(desktop=selected_desktop, profile=selected_profile, force_phase=force_phase or repair))
            return self._run_tracked_phase(item, lambda: self.run_phase_finalize(username=username, force_phase=force_phase or repair))

        if auto or resume or repair or phase is None:
            start_phase = phase if phase and not (resume or repair) else self._resume_start_phase(repair=repair)
            for item in PHASES[PHASES.index(start_phase):]:
                value = self._install_transaction().get("steps", {}).get(item, {})
                if resume and not repair and isinstance(value, dict) and value.get("state") == "completed":
                    continue
                results.append(run_one(item))
            return results
        requested = phase or "extract"
        if requested not in PHASES:
            raise ValueError(f"unsupported phase: {requested}")
        return [run_one(requested)]
