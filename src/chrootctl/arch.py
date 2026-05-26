from __future__ import annotations

from .base_install import BaseInstaller, ReleaseRef

class ArchInstaller(BaseInstaller):
    distro = "arch"
    ROOTFS_URL = "http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz"
    ROOTFS_MD5_URL = f"{ROOTFS_URL}.md5"
    BASE_PACKAGES = ("vim", "net-tools", "sudo", "git", "dbus", "xfce4-terminal")
    DEV_PACKAGES = ("base-devel", "python", "python-pip", "pkgconf")

    def list_versions(self) -> list[ReleaseRef]:
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

    def run_phase_extract(self, *, version: str | None, release: str | None, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("extract", force_phase)
        self.config.chroot_base.mkdir(parents=True, exist_ok=True)
        tarball = self.config.chroot_base / "ArchLinuxARM-aarch64-latest.tar.gz"
        self._download(self.ROOTFS_URL, tarball)
        expected_md5 = self._fetch_text(self.ROOTFS_MD5_URL).split()[0]
        if not self.runner.dry_run:
            self._verify_md5(tarball, expected_md5)
        self.runner.run(["bsdtar", "-xpf", str(tarball)], cwd=self.config.chroot_base)
        for rel in ("dev/pts", "dev/shm", "proc", "sys", "tmp", "media/sdcard", f"home/{self.config.username}"):
            if not self.runner.dry_run:
                (self.config.chroot_base / rel).mkdir(parents=True, exist_ok=True)
        self.mark_phase("extract", version="latest", release_name="rolling", metadata={"tarball": tarball.name, "url": self.ROOTFS_URL})
        return {"phase": "extract", "version": "latest", "release": "rolling", "tarball": tarball.name}

    def _bootstrap_packages(self, profile: str | None) -> tuple[str, ...]:
        packages = list(self.BASE_PACKAGES)
        if profile == "dev":
            packages.extend(self.DEV_PACKAGES)
        packages.extend(self._extra_packages_for_profile(profile))
        return tuple(dict.fromkeys(packages))

    def run_phase_bootstrap(self, *, username: str, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("bootstrap", force_phase)
        user = self._validated_username(username)
        self._ensure_common_bootstrap_prereqs()
        self._require_chroot_commands("pacman")
        self._chroot_shell(r"sed -i 's/^CheckSpace/#CheckSpace/' /etc/pacman.conf || true")
        self._chroot_shell("pacman-key --init || true")
        self._chroot_shell("pacman-key --populate archlinuxarm || true")
        self._chroot_shell("pacman-key --refresh-keys || true")
        self._ensure_android_groups()
        self._chroot_shell("pacman -Syu --noconfirm")
        packages = " ".join(self._bootstrap_packages(profile))
        if packages:
            self._chroot_shell(f"pacman -S --noconfirm {packages}")
        self._ensure_common_user_groups()
        self._ensure_user(
            user,
            "id -u {username} >/dev/null 2>&1 || useradd -m -g users -G wheel,audio,video,storage,aid_inet -s /bin/bash {username}",
        )
        self._write_sudoers(user)
        self._chroot_shell(f"locale-gen {self.config.locale} || true")
        self.mark_phase("bootstrap", metadata={"username": user, "profile": profile or ""})
        return {"phase": "bootstrap", "username": user, "profile": profile or ""}

    def run_phase_desktop(self, *, desktop: str | None, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("desktop", force_phase)
        snapshot = self._create_snapshot("desktop")
        selected_desktop = desktop or "none"
        pkg = {"xfce4": "xfce4 xfce4-terminal", "plasma": "plasma-meta konsole", "none": ""}[selected_desktop]
        if pkg:
            self.controller.mount()
            self.controller.fix_tty()
            self._chroot_shell(f"pacman -S --noconfirm {pkg}")
        self.mark_phase("desktop", metadata={"desktop": selected_desktop, "desktop_snapshot": snapshot or "", "profile": profile or ""})
        return {"phase": "desktop", "desktop": selected_desktop, "snapshot": snapshot or "", "profile": profile or ""}

    def _run_upgrade(self) -> None:
        self._chroot_shell("pacman -Syu --noconfirm")
