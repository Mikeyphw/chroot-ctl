from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from .system import SystemRunner

UBUNTU_SIGNING_FINGERPRINT = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
ARCHLINUXARM_SIGNING_FINGERPRINT = "68B3537F39A313B3E574D06777193F152BDBE6A6"
DEFAULT_KEYSERVER = "hkps://keyserver.ubuntu.com"


class InstallFetchError(RuntimeError):
    """Retrieval failure. Callers may try another download/package source."""


class InstallIntegrityError(RuntimeError):
    """Authenticity/integrity failure. Never treat this as a mirror retry."""


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_from_manifest(manifest: Path, filename: str) -> str:
    for raw in manifest.read_text(encoding="utf-8", errors="strict").splitlines():
        match = re.match(r"^([0-9A-Fa-f]{64})\s+[* ]?(.+)$", raw.strip())
        if match and Path(match.group(2)).name == filename:
            return match.group(1).lower()
    raise InstallIntegrityError(f"authenticated checksum manifest does not contain {filename}")


def verify_sha256(file_path: Path, expected: str) -> None:
    actual = sha256_file(file_path)
    if actual != expected.lower():
        raise InstallIntegrityError(
            f"sha256 mismatch for {file_path.name}: expected {expected.lower()}, got {actual}"
        )


def verify_detached_signature(
    runner: SystemRunner,
    *,
    data: Path,
    signature: Path,
    fingerprint: str,
    keyserver: str = DEFAULT_KEYSERVER,
) -> None:
    expected = fingerprint.replace(" ", "").upper()
    with tempfile.TemporaryDirectory(prefix="chrootctl-gpg-") as temp_dir:
        home = Path(temp_dir)
        home.chmod(0o700)
        try:
            runner.run(
                ["gpg", "--batch", "--homedir", str(home), "--keyserver", keyserver, "--recv-keys", expected],
                timeout=120,
            )
            listed = runner.run(
                ["gpg", "--batch", "--homedir", str(home), "--with-colons", "--fingerprint", expected],
                timeout=30,
            )
        except Exception as exc:
            raise InstallIntegrityError(f"cannot obtain pinned signing key {expected}: {exc}") from exc
        seen = set()
        for line in listed.stdout.splitlines():
            fields = line.split(":")
            if len(fields) > 9 and fields[0] == "fpr":
                seen.add(fields[9].upper())
        if expected not in seen:
            raise InstallIntegrityError(f"retrieved key does not match pinned fingerprint {expected}")
        try:
            verified = runner.run(
                [
                    "gpg", "--batch", "--homedir", str(home), "--status-fd=1",
                    "--verify", str(signature), str(data),
                ],
                timeout=60,
                check=False,
            )
        except Exception as exc:
            raise InstallIntegrityError(f"signature verification failed for {data.name}: {exc}") from exc
        valid_pinned_signature = False
        for line in verified.stdout.splitlines():
            if not line.startswith("[GNUPG:] VALIDSIG "):
                continue
            fields = line.split()
            if len(fields) >= 3 and fields[2].upper() == expected:
                valid_pinned_signature = True
                break
        if not valid_pinned_signature:
            detail = (verified.stderr or verified.stdout or "no valid pinned signature").strip()
            raise InstallIntegrityError(f"signature verification failed for {data.name}: {detail[:1000]}")
