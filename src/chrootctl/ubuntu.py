from __future__ import annotations

import shlex
import shutil
from .base_install import BaseInstaller, LinkParser, ReleaseRef
from .models import InstallBootstrapResult, InstallDesktopResult, InstallExtractResult
from .install_integrity import UBUNTU_SIGNING_FINGERPRINT, checksum_from_manifest, verify_detached_signature, verify_sha256


class UbuntuInstaller(BaseInstaller):
    distro = "ubuntu"
    RELEASE_INDEX_URL = "https://cdimage.ubuntu.com/ubuntu-base/releases/"
    PREREQ_PACKAGES = ("passwd", "login", "libc-bin", "sudo")
    BASE_PACKAGES = ("nano", "vim", "net-tools", "git", "locales", "dbus-x11", "curl", "wget")
    DEV_PACKAGES = ("build-essential", "pkg-config", "python3", "python3-pip")
    DESKTOP_PACKAGES = {
        "xfce4": ("xfce4", "xfce4-terminal", "dbus-x11", "adwaita-icon-theme"),
        "plasma": ("plasma-desktop", "konsole", "dbus-x11", "breeze-icon-theme"),
        "none": (),
    }

    def list_versions(self) -> list[ReleaseRef]:
        html = self._fetch_text_with_mirror_fallback(self.RELEASE_INDEX_URL)
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
        if not self.ready_for_bootstrap():
            return "extract"
        if not (base / "etc/sudoers.d" / self.config.username).exists():
            return "extract"
        if not (base / "usr/share/X11").exists():
            return "bootstrap"
        if not (base / "etc/apt/preferences.d/nosnap.pref").exists():
            return "desktop"
        return "finalize"

    def ready_for_bootstrap(self) -> bool:
        return (self.config.chroot_base / "usr/bin/apt").exists()

    def _resolve_release(self, version: str | None, release: str | None) -> ReleaseRef:
        refs = {r.label: r for r in self.list_versions()}
        for key in [version, release, "24.04.4", "24.04", "noble"]:
            if key and key in refs:
                return refs[key]
        raise ValueError("could not resolve ubuntu release; pass --version or --release")

    def _resolve_tarball(self, ref: ReleaseRef) -> tuple[str, str]:
        html = self._fetch_text_with_mirror_fallback(ref.url)
        parser = LinkParser()
        parser.feed(html)
        suffix_map = {"arm64": "-base-arm64.tar.gz", "amd64": "-base-amd64.tar.gz"}
        suffix = suffix_map.get(self.arch)
        if suffix is None:
            raise RuntimeError(f"unsupported ubuntu target arch: {self.arch}")
        for link in parser.links:
            name = link.split("/")[-1]
            if name.startswith("ubuntu-base-") and name.endswith(suffix):
                return name, f"{ref.url}{name}"
        raise RuntimeError(f"could not find ubuntu-base {self.arch} tarball under {ref.url}")

    def run_phase_extract(
        self, *, version: str | None, release: str | None, force_phase: bool = False,
    ) -> InstallExtractResult:
        self.runner.require_root()
        self.assert_phase_allowed("extract", force_phase)
        ref = self._resolve_release(version, release)
        filename, url = self._resolve_tarball(ref)
        if self.runner.dry_run:
            resolved_version = version or ref.label
            resolved_release = release or ref.label
            self.runner.run(["curl", "--fail", "--location", url, "-o", filename], capture_output=False)
            return InstallExtractResult(version=resolved_version, release=resolved_release, tarball=filename)
        def prepare_rootfs() -> str:
            work_dir = self._new_install_work_dir("download")
            staged_root = self._new_install_work_dir("rootfs")
            try:
                tarball = work_dir / filename
                sums = work_dir / "SHA256SUMS"
                signature = work_dir / "SHA256SUMS.gpg"
                downloaded_url = self._download_with_mirror_fallback(url, tarball)
                self._download(f"{ref.url}SHA256SUMS", sums)
                self._download(f"{ref.url}SHA256SUMS.gpg", signature)
                verify_detached_signature(self.runner, data=sums, signature=signature, fingerprint=UBUNTU_SIGNING_FINGERPRINT)
                verify_sha256(tarball, checksum_from_manifest(sums, filename))
                self.runner.run(["tar", "xpf", str(tarball), "--numeric-owner", "-C", str(staged_root)], capture_output=False)
                self._promote_staged_rootfs(staged_root)
                return downloaded_url
            finally:
                if not self.runner.dry_run:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    if staged_root.exists():
                        shutil.rmtree(staged_root, ignore_errors=True)
        resolved_url = self._run_install_substep("extract", "verified-rootfs-promote", prepare_rootfs) or url
        def initialize_rootfs() -> None:
            for rel in ("dev/pts", "dev/shm", "proc", "sys", "sdcard", "tmp", f"home/{self.config.username}"):
                if not self.runner.dry_run:
                    (self.config.chroot_base / rel).mkdir(parents=True, exist_ok=True)
        self._run_install_substep("extract", "initialize", initialize_rootfs)
        resolved_version = version or ref.label
        resolved_release = release or ref.label
        self.mark_phase("extract", version=resolved_version, release_name=resolved_release, metadata={
            "tarball": filename, "url": resolved_url, "requested_url": url, "mirror": self.current_mirror_selection(),
            "integrity": "openpgp+sha256", "signing_fingerprint": UBUNTU_SIGNING_FINGERPRINT,
        })
        return InstallExtractResult(version=resolved_version, release=resolved_release, tarball=filename)

    def _bootstrap_packages(self, profile: str | None) -> tuple[str, ...]:
        packages = list(self.PREREQ_PACKAGES) + list(self.BASE_PACKAGES)
        if profile == "dev":
            packages.extend(self.DEV_PACKAGES)
        packages.extend(self._extra_packages_for_profile(profile))
        return tuple(dict.fromkeys(packages))

    def _mirror_priority(self) -> list[tuple[str, str]]:
        selected_url = ""
        for item in getattr(self, "_mirror_candidates", ()):
            if item["id"] == self.current_mirror_selection():
                selected_url = item["url"]
                break
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        if selected_url:
            ordered.append((self.current_mirror_selection(), selected_url))
            seen.add(selected_url)
        for item in getattr(self, "_mirror_candidates", ()):
            if item["url"] in seen:
                continue
            ordered.append((item["id"], item["url"]))
            seen.add(item["url"])
        return ordered

    def _apply_apt_mirror(self, mirror_url: str) -> None:
        normalized = mirror_url.rstrip("/")
        self._chroot_shell(
            "for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do "
            "[ -f \"$file\" ] || continue; "
            rf"sed -i 's#https\?://archive\.ubuntu\.com/ubuntu#{normalized}#g; "
            rf"s#https\?://ports\.ubuntu\.com/ubuntu-ports#{normalized}#g; "
            rf"s#https\?://ports\.ubuntu\.com#{normalized}#g' \"$file\"; "
            "done"
        )

    def _apt_with_mirror_fallback(self, command: str) -> None:
        mirrors = self._mirror_priority()
        if not mirrors:
            self._chroot_shell(command)
            return
        last_source_error = ""
        for mirror_id, mirror_url in mirrors:
            self.logger.info("running apt command via mirror %s", mirror_id)
            # A local source-file edit failure is not a mirror failure and must not
            # cause the package operation to be replayed against another mirror.
            self._apply_apt_mirror(mirror_url)
            result = self._chroot_shell_result(command)
            if result.returncode == 0:
                return
            detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part).strip()
            if not _is_apt_source_failure(detail):
                raise RuntimeError(detail or f"apt command failed without a mirror/source error: {command}")
            last_source_error = detail or f"apt source failed via {mirror_id}"
            self.logger.warning("apt source failed via mirror %s: %s", mirror_id, last_source_error)
        raise RuntimeError(f"apt command failed across package mirrors: {last_source_error}")

    def _install_bootstrap_prerequisites(self) -> None:
        packages = " ".join(self.PREREQ_PACKAGES)
        self._apt_with_mirror_fallback(f"DEBIAN_FRONTEND=noninteractive apt install -y {packages}")

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
        self._require_chroot_commands("apt")
        self._run_install_substep("bootstrap", "package-index", lambda: self._apt_with_mirror_fallback("apt update"), resumable=False)
        self._run_install_substep("bootstrap", "prerequisite-packages", self._install_bootstrap_prerequisites)
        self._require_chroot_commands("getent", "groupadd", "usermod", "useradd", "id")
        self._run_install_substep("bootstrap", "android-groups", self._ensure_android_groups)
        self._run_install_substep("bootstrap", "package-upgrade", lambda: self._apt_with_mirror_fallback("DEBIAN_FRONTEND=noninteractive apt -y upgrade"))
        packages = " ".join(self._bootstrap_packages(profile))
        if packages:
            self._run_install_substep("bootstrap", "profile-packages", lambda: self._apt_with_mirror_fallback(f"DEBIAN_FRONTEND=noninteractive apt install -y {packages}"))
        self._run_install_substep("bootstrap", "common-groups", self._ensure_common_user_groups)
        self._run_install_substep("bootstrap", "apt-groups", lambda: (
            self._chroot_shell("id _apt >/dev/null 2>&1 && usermod -g 3003 -G 3003,3004 -a _apt || true"),
            self._chroot_shell("usermod -G 3003 -a root || true"),
        ))
        self._run_install_substep(
            "bootstrap", "user",
            lambda: self._ensure_user(user, "id -u {username} >/dev/null 2>&1 || useradd -m -g users -G wheel,audio,video,storage,aid_inet -s /bin/bash {username}"),
        )
        self._run_install_substep("bootstrap", "sudoers", lambda: self._write_sudoers(user))
        self._run_install_substep("bootstrap", "locale", lambda: self._chroot_shell(f"locale-gen {shlex.quote(self.config.locale)}"))
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
        packages = self.DESKTOP_PACKAGES[selected_desktop]
        if packages:
            self.controller.mount(); self.controller.fix_tty()
            package_list = " ".join(packages)
            self._run_install_substep("desktop", "packages", lambda: self._apt_with_mirror_fallback(f"DEBIAN_FRONTEND=noninteractive apt install --no-install-recommends -y {package_list}"))
        pref = self.config.chroot_base / "etc/apt/preferences.d/nosnap.pref"
        def apply_policy() -> None:
            if not self.runner.dry_run:
                pref.parent.mkdir(parents=True, exist_ok=True)
                pref.write_text("Package: snapd\nPin: release a=*\nPin-Priority: -10\n", encoding="utf-8")
            self._chroot_shell("apt-get -y autopurge snapd || true")
        self._run_install_substep("desktop", "policy", apply_policy)
        self.mark_phase("desktop", metadata={"desktop": selected_desktop, "desktop_snapshot": snapshot or "", "profile": profile or ""})
        return InstallDesktopResult(desktop=selected_desktop, snapshot=snapshot or "", profile=profile or "")

    def _run_upgrade(self) -> None:
        self._apt_with_mirror_fallback("apt update")
        self._apt_with_mirror_fallback("DEBIAN_FRONTEND=noninteractive apt -y upgrade")
        self._chroot_shell("DEBIAN_FRONTEND=noninteractive apt -y autoremove")


def _is_apt_source_failure(detail: str) -> bool:
    text = detail.lower()
    markers = (
        "temporary failure resolving", "could not resolve", "failed to fetch",
        "connection timed out", "connection refused", "network is unreachable",
        "could not connect", "tls connection", "certificate verification failed",
        "404  not found", "403  forbidden", "does not have a release file",
        "release file", "hash sum mismatch",
    )
    return any(marker in text for marker in markers)
