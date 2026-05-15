from __future__ import annotations

from .base_install import BaseInstaller, ReleaseRef

class ArchInstaller(BaseInstaller):
    distro = "arch"
    ROOTFS_URL = "http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz"

    def list_versions(self) -> list[ReleaseRef]:
        return [ReleaseRef("latest", self.ROOTFS_URL)]

    def infer_phase_from_filesystem(self):
        base = self.config.chroot_base
        if not (base / "etc/os-release").exists():
            return "extract"
        if not (base / "etc/sudoers.d" / self.config.username).exists():
            return "extract"
        if not (base / "usr/bin/startxfce4").exists() and not (base / "usr/bin/xfce4-session").exists():
            return "bootstrap"
        return "finalize"

    def run_phase_extract(self, *, version: str | None, release: str | None, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("extract", force_phase)
        self.config.chroot_base.mkdir(parents=True, exist_ok=True)
        tarball = self.config.chroot_base / "ArchLinuxARM-aarch64-latest.tar.gz"
        self.runner.run(["curl", "-L", self.ROOTFS_URL, "-o", str(tarball)])
        self.runner.run(["bsdtar", "-xpf", str(tarball)], cwd=self.config.chroot_base)
        for rel in ("dev/pts", "dev/shm", "proc", "sys", "tmp", "media/sdcard", f"home/{self.config.username}"):
            if not self.runner.dry_run:
                (self.config.chroot_base / rel).mkdir(parents=True, exist_ok=True)
        self.mark_phase("extract", version="latest", release_name="rolling", metadata={"tarball": tarball.name, "url": self.ROOTFS_URL})
        return {"phase": "extract", "version": "latest", "release": "rolling", "tarball": tarball.name}

    def run_phase_bootstrap(self, *, username: str, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("bootstrap", force_phase)
        self.controller.mount()
        self.controller.fix_tty()
        self._chroot_shell('printf "nameserver 8.8.8.8\\n" > /etc/resolv.conf')
        self._chroot_shell('printf "127.0.0.1 localhost\\n::1 localhost\\n" > /etc/hosts')
        self._chroot_shell(r"sed -i 's/^CheckSpace/#CheckSpace/' /etc/pacman.conf || true")
        self._chroot_shell("pacman-key --init || true")
        self._chroot_shell("pacman-key --populate archlinuxarm || true")
        self._chroot_shell("pacman-key --refresh-keys || true")
        for group_name, gid in (("aid_inet", 3003), ("aid_net_raw", 3004), ("aid_graphics", 1003)):
            self._chroot_shell(f'getent group {group_name} >/dev/null || groupadd -g {gid} {group_name}')
        self._chroot_shell("pacman -Syu --noconfirm")
        self._chroot_shell("pacman -S --noconfirm vim net-tools sudo git dbus xfce4-terminal")
        self._chroot_shell("getent group storage >/dev/null || groupadd storage")
        self._chroot_shell("getent group wheel >/dev/null || groupadd wheel")
        self._chroot_shell(f"id -u {username} >/dev/null 2>&1 || useradd -m -g users -G wheel,audio,video,storage,aid_inet -s /bin/bash {username}")
        sudoers = self.config.chroot_base / "etc" / "sudoers.d" / username
        if not self.runner.dry_run:
            sudoers.parent.mkdir(parents=True, exist_ok=True)
            sudoers.write_text(f"{username} ALL=(ALL:ALL) ALL\n", encoding="utf-8")
            sudoers.chmod(0o440)
        self._chroot_shell("locale-gen en_US.UTF-8 || true")
        self.mark_phase("bootstrap", metadata={"username": username})
        return {"phase": "bootstrap", "username": username}

    def run_phase_desktop(self, *, desktop: str, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("desktop", force_phase)
        pkg = {"xfce4": "xfce4 xfce4-terminal", "plasma": "plasma-meta konsole", "none": ""}[desktop]
        if pkg:
            self.controller.mount()
            self.controller.fix_tty()
            self._chroot_shell(f"pacman -S --noconfirm {pkg}")
        self.mark_phase("desktop", metadata={"desktop": desktop})
        return {"phase": "desktop", "desktop": desktop}
