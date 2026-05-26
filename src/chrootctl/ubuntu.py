from __future__ import annotations

from .base_install import BaseInstaller, LinkParser, ReleaseRef

class UbuntuInstaller(BaseInstaller):
    distro = "ubuntu"
    RELEASE_INDEX_URL = "https://cdimage.ubuntu.com/ubuntu-base/releases/"
    PREREQ_PACKAGES = ("passwd", "login", "libc-bin", "sudo")
    BASE_PACKAGES = ("nano", "vim", "net-tools", "git", "locales", "dbus-x11", "curl", "wget")
    DEV_PACKAGES = ("build-essential", "pkg-config", "python3", "python3-pip")

    def list_versions(self) -> list[ReleaseRef]:
        html = self._fetch_text(self.RELEASE_INDEX_URL)
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
        html = self._fetch_text(ref.url)
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
        self._download(url, tarball)
        self.runner.run(["tar", "xpvf", str(tarball), "--numeric-owner"], cwd=self.config.chroot_base)
        for rel in ("dev/pts", "dev/shm", "proc", "sys", "sdcard", "tmp", f"home/{self.config.username}"):
            if not self.runner.dry_run:
                (self.config.chroot_base / rel).mkdir(parents=True, exist_ok=True)
        self.mark_phase("extract", version=version or ref.label, release_name=release or ref.label, metadata={"tarball": filename, "url": url})
        return {"phase": "extract", "version": version or ref.label, "release": release or ref.label, "tarball": filename}

    def _bootstrap_packages(self, profile: str | None) -> tuple[str, ...]:
        packages = list(self.PREREQ_PACKAGES) + list(self.BASE_PACKAGES)
        if profile == "dev":
            packages.extend(self.DEV_PACKAGES)
        packages.extend(self._extra_packages_for_profile(profile))
        return tuple(dict.fromkeys(packages))

    def _install_bootstrap_prerequisites(self) -> None:
        packages = " ".join(self.PREREQ_PACKAGES)
        self._chroot_shell(f"DEBIAN_FRONTEND=noninteractive apt install -y {packages}")

    def run_phase_bootstrap(self, *, username: str, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("bootstrap", force_phase)
        user = self._validated_username(username)
        self._ensure_common_bootstrap_prereqs()
        self._chroot_shell("apt update")
        self._install_bootstrap_prerequisites()
        self._require_chroot_commands("getent", "groupadd", "usermod", "useradd", "id")
        self._ensure_android_groups()
        self._chroot_shell("DEBIAN_FRONTEND=noninteractive apt -y upgrade")
        packages = " ".join(self._bootstrap_packages(profile))
        if packages:
            self._chroot_shell(f"DEBIAN_FRONTEND=noninteractive apt install -y {packages}")
        self._ensure_common_user_groups()
        self._chroot_shell("id _apt >/dev/null 2>&1 && usermod -g 3003 -G 3003,3004 -a _apt || true")
        self._chroot_shell("usermod -G 3003 -a root || true")
        self._ensure_user(
            user,
            "id -u {username} >/dev/null 2>&1 || useradd -m -g users -G wheel,audio,video,storage,aid_inet -s /bin/bash {username}",
        )
        self._write_sudoers(user)
        self._chroot_shell(f"locale-gen {self.config.locale}")
        self.mark_phase("bootstrap", metadata={"username": user, "profile": profile or ""})
        return {"phase": "bootstrap", "username": user, "profile": profile or ""}

    def run_phase_desktop(self, *, desktop: str | None, profile: str | None = None, force_phase: bool = False) -> dict[str, str]:
        self.runner.require_root()
        self.assert_phase_allowed("desktop", force_phase)
        snapshot = self._create_snapshot("desktop")
        selected_desktop = desktop or "none"
        pkg = {"xfce4": "xubuntu-desktop", "plasma": "kubuntu-desktop", "none": ""}[selected_desktop]
        if pkg:
            self.controller.mount()
            self.controller.fix_tty()
            self._chroot_shell(f"DEBIAN_FRONTEND=noninteractive apt install -y {pkg}")
        pref = self.config.chroot_base / "etc/apt/preferences.d/nosnap.pref"
        if not self.runner.dry_run:
            pref.parent.mkdir(parents=True, exist_ok=True)
            pref.write_text("Package: snapd\nPin: release a=*\nPin-Priority: -10\n", encoding="utf-8")
        self._chroot_shell("apt-get -y autopurge snapd || true")
        self.mark_phase("desktop", metadata={"desktop": selected_desktop, "desktop_snapshot": snapshot or "", "profile": profile or ""})
        return {"phase": "desktop", "desktop": selected_desktop, "snapshot": snapshot or "", "profile": profile or ""}

    def _run_upgrade(self) -> None:
        self._chroot_shell("apt update")
        self._chroot_shell("DEBIAN_FRONTEND=noninteractive apt -y upgrade")
        self._chroot_shell("DEBIAN_FRONTEND=noninteractive apt -y autoremove")
