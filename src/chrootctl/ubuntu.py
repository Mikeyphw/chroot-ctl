from __future__ import annotations

from .base_install import BaseInstaller, LinkParser, ReleaseRef
from urllib.request import urlopen

class UbuntuInstaller(BaseInstaller):
    distro = "ubuntu"
    RELEASE_INDEX_URL = "https://cdimage.ubuntu.com/ubuntu-base/releases/"

    def list_versions(self) -> list[ReleaseRef]:
        with urlopen(self.RELEASE_INDEX_URL) as response:
            html = response.read().decode("utf-8", errors="replace")
        parser = LinkParser()
        parser.feed(html)
        refs: list[ReleaseRef] = []
        for link in parser.links:
            cleaned = link.strip("/")
            if cleaned and (cleaned.replace(".", "").isdigit() or cleaned.isalpha()):
                refs.append(ReleaseRef(cleaned, f"{self.RELEASE_INDEX_URL}{cleaned}/release/"))
        uniq = {ref.label: ref for ref in refs}
        return [uniq[k] for k in sorted(uniq.keys())]

    def infer_phase_from_filesystem(self):
        base = self.config.chroot_base
        if not (base / "etc/os-release").exists():
            return "extract"
        if not (base / "etc/sudoers.d" / self.config.username).exists():
            return "extract"
        if not (base / "usr/share/X11").exists():
            return "bootstrap"
        if not (base / "etc/apt/preferences.d/nosnap.pref").exists():
            return "desktop"
        return "finalize"

    def _resolve_release(self, version: str | None, release: str | None) -> ReleaseRef:
        refs = {r.label: r for r in self.list_versions()}
        for key in [version, release, "24.04.4", "24.04", "noble"]:
            if key and key in refs:
                return refs[key]
        raise ValueError("could not resolve Ubuntu release")

    def _resolve_tarball(self, ref: ReleaseRef) -> tuple[str, str]:
        with urlopen(ref.url) as response:
            html = response.read().decode("utf-8", errors="replace")
        parser = LinkParser()
        parser.feed(html)
        tarballs = [link for link in parser.links if link.endswith("-base-arm64.tar.gz")]
        if not tarballs:
            raise ValueError("no Ubuntu arm64 rootfs tarball found")
        name = tarballs[0].split("/")[-1]
        return name, f"{ref.url}{name}"

    def run_phase_extract(self, *, version: str | None, release: str | None, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("extract", force_phase)
        ref = self._resolve_release(version, release)
        filename, url = self._resolve_tarball(ref)
        self.config.chroot_base.mkdir(parents=True, exist_ok=True)
        tarball = self.config.chroot_base / filename
        self.runner.run(["curl", "-L", url, "-o", str(tarball)])
        self.runner.run(["tar", "xpvf", str(tarball), "--numeric-owner"], cwd=self.config.chroot_base)
        for rel in ("dev/pts", "dev/shm", "proc", "sys", "sdcard", "tmp", f"home/{self.config.username}"):
            if not self.runner.dry_run:
                (self.config.chroot_base / rel).mkdir(parents=True, exist_ok=True)
        self.mark_phase("extract", version=version or ref.label, release_name=release or ref.label, metadata={"tarball": filename, "url": url})
        return {"phase": "extract", "version": version or ref.label, "release": release or ref.label, "tarball": filename}

    def run_phase_bootstrap(self, *, username: str, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("bootstrap", force_phase)
        self.controller.mount()
        self.controller.fix_tty()
        self._chroot_shell('printf "nameserver 8.8.8.8\\n" > /etc/resolv.conf')
        self._chroot_shell('printf "127.0.0.1 localhost\\n::1 localhost\\n" > /etc/hosts')
        for group_name, gid in (("aid_inet", 3003), ("aid_net_raw", 3004), ("aid_graphics", 1003)):
            self._chroot_shell(f'getent group {group_name} >/dev/null || groupadd -g {gid} {group_name}')
        self._chroot_shell("apt update")
        self._chroot_shell("DEBIAN_FRONTEND=noninteractive apt -y upgrade")
        self._chroot_shell("DEBIAN_FRONTEND=noninteractive apt install -y nano vim net-tools sudo git locales dbus-x11 curl wget")
        self._chroot_shell("getent group storage >/dev/null || groupadd storage")
        self._chroot_shell("getent group wheel >/dev/null || groupadd wheel")
        self._chroot_shell("id _apt >/dev/null 2>&1 && usermod -g 3003 -G 3003,3004 -a _apt || true")
        self._chroot_shell("usermod -G 3003 -a root || true")
        self._chroot_shell(f"id -u {username} >/dev/null 2>&1 || useradd -m -g users -G wheel,audio,video,storage,aid_inet -s /bin/bash {username}")
        sudoers = self.config.chroot_base / "etc" / "sudoers.d" / username
        if not self.runner.dry_run:
            sudoers.parent.mkdir(parents=True, exist_ok=True)
            sudoers.write_text(f"{username} ALL=(ALL:ALL) ALL\n", encoding="utf-8")
            sudoers.chmod(0o440)
        self._chroot_shell("locale-gen en_US.UTF-8")
        self.mark_phase("bootstrap", metadata={"username": username})
        return {"phase": "bootstrap", "username": username}

    def run_phase_desktop(self, *, desktop: str, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("desktop", force_phase)
        pkg = {"xfce4": "xubuntu-desktop", "plasma": "kubuntu-desktop", "none": ""}[desktop]
        if pkg:
            self.controller.mount()
            self.controller.fix_tty()
            self._chroot_shell(f"DEBIAN_FRONTEND=noninteractive apt install -y {pkg}")
        pref = self.config.chroot_base / "etc/apt/preferences.d/nosnap.pref"
        if not self.runner.dry_run:
            pref.parent.mkdir(parents=True, exist_ok=True)
            pref.write_text("Package: snapd\nPin: release a=*\nPin-Priority: -10\n", encoding="utf-8")
        self._chroot_shell("apt-get -y autopurge snapd || true")
        self.mark_phase("desktop", metadata={"desktop": desktop})
        return {"phase": "desktop", "desktop": desktop}
