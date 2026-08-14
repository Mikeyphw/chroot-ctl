from __future__ import annotations

import shlex
import shutil
from .base_install import BaseInstaller, ReleaseRef
from .models import InstallBootstrapResult, InstallDesktopResult, InstallExtractResult
from .install_integrity import ARCHLINUXARM_SIGNING_FINGERPRINT, verify_detached_signature


class ArchInstaller(BaseInstaller):
    distro = "arch"
    default_arch = "arm64"
    ROOTFS_URL = "https://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz"
    BASE_PACKAGES = ("vim", "net-tools", "sudo", "git", "dbus", "xfce4-terminal")
    DEV_PACKAGES = ("base-devel", "python", "python-pip", "pkgconf")

    def list_versions(self) -> list[ReleaseRef]:
        if self.arch != "arm64":
            raise RuntimeError("Arch rootfs export currently supports arm64 only")
        return [ReleaseRef("latest", self.ROOTFS_URL)]

    def infer_phase_from_filesystem(self):
        base = self.config.chroot_base
        if not (base / "etc/os-release").exists():
            return "extract"
        if not self.ready_for_bootstrap():
            return "extract"
        if not (base / "etc/sudoers.d" / self.config.username).exists():
            return "extract"
        if not (base / "usr/bin/startxfce4").exists() and not (base / "usr/bin/xfce4-session").exists():
            return "bootstrap"
        return "finalize"

    def ready_for_bootstrap(self) -> bool:
        return (self.config.chroot_base / "usr/bin/pacman").exists()

    def run_phase_extract(
        self, *, version: str | None, release: str | None, force_phase: bool = False,
    ) -> InstallExtractResult:
        self.runner.require_root()
        self.assert_phase_allowed("extract", force_phase)
        if self.arch != "arm64":
            raise RuntimeError(f"Arch Linux ARM supports arm64 only; requested {self.arch}")
        filename = self.ROOTFS_URL.rsplit("/", 1)[-1]
        if self.runner.dry_run:
            self.runner.run(["curl", "--fail", "--location", self.ROOTFS_URL, "-o", filename], capture_output=False)
            return InstallExtractResult(version="latest", release="rolling", tarball=filename)
        def prepare_rootfs() -> str:
            work_dir = self._new_install_work_dir("download")
            staged_root = self._new_install_work_dir("rootfs")
            try:
                tarball = work_dir / filename
                signature = work_dir / f"{filename}.sig"
                downloaded_url = self._download_with_mirror_fallback(self.ROOTFS_URL, tarball)
                self._download(f"{self.ROOTFS_URL}.sig", signature)
                verify_detached_signature(self.runner, data=tarball, signature=signature, fingerprint=ARCHLINUXARM_SIGNING_FINGERPRINT)
                self.runner.run(["bsdtar", "-xpf", str(tarball), "-C", str(staged_root)], capture_output=False)
                self._promote_staged_rootfs(staged_root)
                return downloaded_url
            finally:
                if not self.runner.dry_run:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    if staged_root.exists():
                        shutil.rmtree(staged_root, ignore_errors=True)
        resolved_url = self._run_install_substep("extract", "verified-rootfs-promote", prepare_rootfs) or self.ROOTFS_URL
        def initialize_rootfs() -> None:
            for rel in ("dev/pts", "dev/shm", "proc", "sys", "tmp", "media/sdcard", f"home/{self.config.username}"):
                if not self.runner.dry_run:
                    (self.config.chroot_base / rel).mkdir(parents=True, exist_ok=True)
        self._run_install_substep("extract", "initialize", initialize_rootfs)
        self.mark_phase("extract", version="latest", release_name="rolling", metadata={
            "tarball": filename, "url": resolved_url, "requested_url": self.ROOTFS_URL, "mirror": self.current_mirror_selection(),
            "integrity": "openpgp", "signing_fingerprint": ARCHLINUXARM_SIGNING_FINGERPRINT,
        })
        return InstallExtractResult(version="latest", release="rolling", tarball=filename)

    def _bootstrap_packages(self, profile: str | None) -> tuple[str, ...]:
        packages = list(self.BASE_PACKAGES)
        if profile == "dev":
            packages.extend(self.DEV_PACKAGES)
        packages.extend(self._extra_packages_for_profile(profile))
        return tuple(dict.fromkeys(packages))

    def run_phase_bootstrap(
        self,
        *,
        username: str,
        profile: str | None = None,
        force_phase: bool = False,
    ) -> InstallBootstrapResult:
        self.runner.require_root()
        self._ensure_chroot_execution_supported()
        self.assert_phase_allowed("bootstrap", force_phase)
        user = self._validated_username(username)
        self._run_install_substep("bootstrap", "runtime-prereqs", self._ensure_common_bootstrap_prereqs, resumable=False)
        self._require_chroot_commands("pacman")
        self._run_install_substep("bootstrap", "pacman-config", lambda: self._chroot_shell(r"sed -i 's/^CheckSpace/#CheckSpace/' /etc/pacman.conf || true"))
        self._run_install_substep("bootstrap", "keyring", lambda: (
            self._chroot_shell("pacman-key --init || true"),
            self._chroot_shell("pacman-key --populate archlinuxarm || true"),
            self._chroot_shell("pacman-key --refresh-keys || true"),
        ))
        self._run_install_substep("bootstrap", "android-groups", self._ensure_android_groups)
        self._run_install_substep("bootstrap", "package-upgrade", lambda: self._chroot_shell("pacman -Syu --noconfirm"))
        packages = " ".join(self._bootstrap_packages(profile))
        if packages:
            self._run_install_substep("bootstrap", "profile-packages", lambda: self._chroot_shell(f"pacman -S --noconfirm {packages}"))
        self._run_install_substep("bootstrap", "common-groups", self._ensure_common_user_groups)
        self._run_install_substep(
            "bootstrap", "user",
            lambda: self._ensure_user(user, "id -u {username} >/dev/null 2>&1 || useradd -m -g users -G wheel,audio,video,storage,aid_inet -s /bin/bash {username}"),
        )
        self._run_install_substep("bootstrap", "sudoers", lambda: self._write_sudoers(user))
        self._run_install_substep("bootstrap", "locale", lambda: self._chroot_shell(f"locale-gen {shlex.quote(self.config.locale)} || true"))
        self.mark_phase("bootstrap", metadata={"username": user, "profile": profile or ""})
        return InstallBootstrapResult(username=user, profile=profile or "")

    def run_phase_desktop(
        self,
        *,
        desktop: str | None,
        profile: str | None = None,
        force_phase: bool = False,
    ) -> InstallDesktopResult:
        self.runner.require_root()
        self._ensure_chroot_execution_supported()
        self.assert_phase_allowed("desktop", force_phase)
        snapshot = self._create_snapshot("desktop")
        selected_desktop = desktop or "none"
        pkg = {"xfce4": "xfce4 xfce4-terminal", "plasma": "plasma-meta konsole", "none": ""}[selected_desktop]
        if pkg:
            self.controller.mount(); self.controller.fix_tty()
            self._run_install_substep("desktop", "packages", lambda: self._chroot_shell(f"pacman -S --noconfirm {pkg}"))
        self.mark_phase("desktop", metadata={"desktop": selected_desktop, "desktop_snapshot": snapshot or "", "profile": profile or ""})
        return InstallDesktopResult(desktop=selected_desktop, snapshot=snapshot or "", profile=profile or "")

    def _run_upgrade(self) -> None:
        self._chroot_shell("pacman -Syu --noconfirm")
