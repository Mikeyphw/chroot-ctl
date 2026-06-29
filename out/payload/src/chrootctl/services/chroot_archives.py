from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import AppError
from ..models import ChrootArchiveInspection, ChrootExportResult, ChrootImportResult, ChrootRecord, ChrootRemovalResult, ChrootRenameResult
from ..registry import ChrootRegistry

CHROOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_chroot_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise RuntimeError("new chroot name is required")
    if not CHROOT_NAME_PATTERN.fullmatch(normalized):
        raise RuntimeError(f"invalid chroot name: {name!r}")
    return normalized


def record_from_registry(row: dict[str, object]) -> ChrootRecord:
    return ChrootRecord(
        name=str(row.get("name", "")),
        distro=str(row.get("distro", "")),
        path=str(row.get("path", "")),
        release_name=str(row.get("release_name", "")),
        version=str(row.get("version", "")),
        phase=str(row.get("phase", "")),
        installed=bool(row.get("installed")),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


def mount_summary(config) -> str:
    mounts: list[str] = []
    for mount in config.media_mounts + config.extra_bind_mounts:
        if mount.enabled:
            mode = "ro" if mount.read_only else "rw"
            mounts.append(f"{mount.source}->{mount.target}({mode})")
    return ", ".join(mounts) or "default"

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_checksum_file(path: Path) -> str:
    line = path.read_text(encoding="utf-8").strip().splitlines()[0]
    return line.split()[0].strip()


def _next_available_name(name: str, registry: ChrootRegistry, config) -> str:
    counter = 2
    candidate = name
    while registry.get(candidate) is not None or config.for_chroot(candidate).chroot_base.exists():
        candidate = f"{name}-{counter}"
        counter += 1
    return candidate


def record_from_registry(row: dict[str, object]) -> ChrootRecord:
    return ChrootRecord(
        name=str(row.get("name", "")),
        distro=str(row.get("distro", "")),
        path=str(row.get("path", "")),
        release_name=str(row.get("release_name", "")),
        version=str(row.get("version", "")),
        phase=str(row.get("phase", "")),
        installed=bool(row.get("installed")),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


def validate_chroot_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise RuntimeError("new chroot name is required")
    if not CHROOT_NAME_PATTERN.fullmatch(normalized):
        raise RuntimeError(f"invalid chroot name: {name!r}")
    return normalized


def mount_summary(config) -> str:
    mounts: list[str] = []
    for mount in config.media_mounts + config.extra_bind_mounts:
        if mount.enabled:
            mode = "ro" if mount.read_only else "rw"
            mounts.append(f"{mount.source}->{mount.target}({mode})")
    return ", ".join(mounts) or "default"


def remove_chroot(config, registry: ChrootRegistry, runner, logger: Any, name: str) -> ChrootRemovalResult:
    record = registry.get(name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {name}")
    target_config = config.for_chroot(name)
    from ..controller import ChrootController

    controller = ChrootController(target_config, runner, logger)
    unmount_result = controller.unmount()
    target_path = Path(str(record["path"]))
    resolved_root = target_config.chroot_root.resolve()
    resolved_target = target_path.resolve(strict=False)
    if resolved_root not in resolved_target.parents and resolved_root != resolved_target:
        raise RuntimeError(f"refusing to delete path outside chroot root: {resolved_target}")
    if runner.dry_run:
        return ChrootRemovalResult(
            name=name,
            removed=False,
            unmounted_success=unmount_result.success,
            unmounted_failed=unmount_result.failed,
        )
    if target_path.exists():
        import shutil

        shutil.rmtree(target_path)
    registry.delete(name)
    return ChrootRemovalResult(
        name=name,
        removed=True,
        unmounted_success=unmount_result.success,
        unmounted_failed=unmount_result.failed,
    )


def rename_chroot(config, registry: ChrootRegistry, old_name: str, new_name: str) -> ChrootRenameResult:
    normalized_new_name = validate_chroot_name(new_name)
    record = registry.get(old_name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {old_name}")
    if registry.get(normalized_new_name) is not None:
        raise RuntimeError(f"destination chroot already exists: {normalized_new_name}")
    old_config = config.for_chroot(old_name)
    new_config = config.for_chroot(normalized_new_name)
    registry_path = Path(str(record["path"])).resolve(strict=False)
    expected_path = old_config.chroot_base.resolve(strict=False)
    if registry_path != expected_path:
        raise RuntimeError(
            f"registry path mismatch for {old_name}: expected {expected_path}, found {registry_path}"
        )
    if new_config.chroot_base.exists():
        raise RuntimeError(f"destination path already exists: {new_config.chroot_base}")
    if old_config.chroot_base.exists():
        old_config.chroot_base.rename(new_config.chroot_base)
    registry.rename(old_name, normalized_new_name, new_path=str(new_config.chroot_base))
    return ChrootRenameResult(old_name=old_name, new_name=normalized_new_name, renamed=True)

def _tar_with_zstd_args(*, create: bool, archive: Path, cwd: Path, members: list[str]) -> list[str]:
    base = ["tar", "--zstd", "-cpf" if create else "-xpf", str(archive)]
    if not create:
        base = ["tar", "--zstd", "-xpf", str(archive)]
    return [*base, *members]


def _read_export_manifest(archive: Path, *, password: str | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="chrootctl-import-manifest-") as tmp:
        tmpdir = Path(tmp)
        source_archive = archive
        if archive.name.endswith(".enc"):
            source_archive = _decrypt_archive(archive, password, tmpdir)
        result = subprocess.run(
            ["tar", "--zstd", "-xpf", str(source_archive), "-C", str(tmpdir), ".chrootctl-export.json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to read export manifest from {archive}")
        manifest_path = tmpdir / ".chrootctl-export.json"
        if not manifest_path.exists():
            raise RuntimeError(f"archive is missing .chrootctl-export.json: {archive}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))


def inspect_chroot_archive(archive: Path, *, registry: ChrootRegistry | None = None, password: str | None = None) -> ChrootArchiveInspection:
    archive_path = archive.expanduser().resolve()
    if not archive_path.exists():
        raise RuntimeError(f"archive does not exist: {archive_path}")
    encrypted = archive_path.name.endswith(".enc")
    manifest = _read_export_manifest(archive_path, password=password)
    source_name = validate_chroot_name(str(manifest.get("name") or manifest.get("path_name") or archive_path.stem.replace(".tar", "")))
    suggested_name = source_name
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    checksum = None
    checksum_verified = None
    if checksum_path.exists():
        checksum = _read_checksum_file(checksum_path)
        checksum_verified = checksum == _sha256_file(archive_path)
    target_exists = bool(registry.get(suggested_name)) if registry is not None else False
    created_at = datetime.fromtimestamp(archive_path.stat().st_mtime, tz=timezone.utc).isoformat()
    return ChrootArchiveInspection(
        archive=archive_path,
        source_name=source_name,
        suggested_name=suggested_name,
        path_name=str(manifest.get("path_name") or source_name),
        distro=str(manifest.get("distro", "")),
        arch=str(manifest.get("arch", "")),
        release_name=str(manifest.get("release_name", "")),
        version=str(manifest.get("version", "")),
        phase=str(manifest.get("phase", "")),
        installed=bool(manifest.get("installed")),
        metadata=dict(manifest.get("metadata", {})),
        size_bytes=archive_path.stat().st_size,
        created_at=created_at,
        checksum=checksum,
        checksum_path=checksum_path if checksum_path.exists() else None,
        checksum_verified=checksum_verified,
        encrypted=encrypted,
        target_exists=target_exists,
    )


def export_chroot(config, registry: ChrootRegistry, runner, logger: Any, name: str, *, archive: Path | None = None, password: str | None = None) -> ChrootExportResult:
    record = registry.get(name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {name}")
    target_config = config.for_chroot(name)
    chroot_path = Path(str(record["path"])).resolve(strict=False)
    if not chroot_path.exists():
        raise RuntimeError(f"chroot path does not exist: {chroot_path}")
    archive_path = (archive or Path.cwd() / f"{name}.tar.zst").expanduser().resolve()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "distro": str(record.get("distro", "")),
        "arch": str(record.get("arch") or getattr(target_config, "target_arch", "arm64")),
        "release_name": str(record.get("release_name", "")),
        "version": str(record.get("version", "")),
        "phase": str(record.get("phase", "")),
        "installed": bool(record.get("installed")),
        "metadata": record.get("metadata", {}),
        "path_name": chroot_path.name,
    }
    with tempfile.TemporaryDirectory(prefix="chrootctl-export-") as tmp:
        tmpdir = Path(tmp)
        manifest_path = tmpdir / ".chrootctl-export.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        result = subprocess.run(
            [
                "tar",
                "--zstd",
                "-cpf",
                str(archive_path),
                "-C",
                str(chroot_path.parent),
                chroot_path.name,
                "-C",
                str(tmpdir),
                manifest_path.name,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to export {name} to {archive_path}")
    encrypted = False
    if password:
        archive_path = _encrypt_archive(archive_path, password)
        encrypted = True
    checksum = _sha256_file(archive_path)
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    checksum_path.write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    logger.info("exported chroot %s to %s", name, archive_path)
    return ChrootExportResult(name=name, archive=archive_path, arch=str(manifest["arch"]), checksum=checksum, checksum_path=checksum_path, encrypted=encrypted)


def import_chroot(
    config,
    registry: ChrootRegistry,
    runner,
    logger: Any,
    *,
    archive: Path,
    name: str | None = None,
    conflict: str = "rename",
    password: str | None = None,
    post_import: str = "register",
) -> ChrootImportResult:
    archive_path = archive.expanduser().resolve()
    if not archive_path.exists():
        raise RuntimeError(f"archive does not exist: {archive_path}")
    encrypted = archive_path.name.endswith(".enc")
    manifest = _read_export_manifest(archive_path, password=password)
    source_name = validate_chroot_name(str(manifest.get("name") or manifest.get("path_name") or archive_path.stem.replace(".tar", "")))
    requested_name = validate_chroot_name(name or source_name)
    target_name = requested_name
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    checksum_verified = None
    if checksum_path.exists():
        checksum_verified = _read_checksum_file(checksum_path) == _sha256_file(archive_path)
        if not checksum_verified:
            raise RuntimeError(f"checksum verification failed for {archive_path.name}")
    if conflict not in {"rename", "overwrite"}:
        raise RuntimeError(f"unsupported conflict strategy: {conflict}")
    if registry.get(target_name) is not None or config.for_chroot(target_name).chroot_base.exists():
        if conflict == "overwrite":
            existing = config.for_chroot(target_name)
            if existing.chroot_base.exists():
                shutil.rmtree(existing.chroot_base)
            try:
                registry.delete(target_name)
            except Exception:
                pass
        else:
            target_name = _next_available_name(requested_name, registry, config)
    target_config = config.for_chroot(target_name)
    if target_config.chroot_base.exists():
        raise RuntimeError(f"destination path already exists: {target_config.chroot_base}")
    target_config.chroot_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chrootctl-import-") as tmp:
        tmpdir = Path(tmp)
        source_archive = archive_path
        if encrypted:
            source_archive = _decrypt_archive(archive_path, password, tmpdir)
        result = subprocess.run(
            ["tar", "--zstd", "-xpf", str(source_archive), "-C", str(tmpdir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to extract {archive_path}")
        extracted_path = tmpdir / str(manifest.get("path_name") or source_name)
        if not extracted_path.exists():
            raise RuntimeError(f"archive is missing extracted chroot directory: {extracted_path.name}")
        shutil.move(str(extracted_path), str(target_config.chroot_base))
    registry.upsert(
        name=target_name,
        distro=str(manifest.get("distro", "")),
        path=str(target_config.chroot_base),
        arch=str(manifest.get("arch", getattr(target_config, "target_arch", "arm64"))),
        release_name=str(manifest.get("release_name", "")),
        version=str(manifest.get("version", "")),
        phase=str(manifest.get("phase", "extract") or "extract"),
        installed=bool(manifest.get("installed")),
        metadata=dict(manifest.get("metadata", {})),
    )
    validation_ok = None
    validation_summary = ""
    if post_import not in {"register", "validate", "fixups", "shell"}:
        raise RuntimeError(f"unsupported post-import action: {post_import}")
    if post_import in {"validate", "fixups", "shell"}:
        validation = validate_imported_chroot(target_config.chroot_base, arch=str(manifest.get("arch", getattr(target_config, "target_arch", "arm64"))))
        validation_ok = bool(validation.get("ok"))
        validation_summary = "; ".join(validation.get("messages", ())) or ("ready" if validation_ok else "validation failed")
        if post_import == "fixups":
            validation_summary = f"{validation_summary}; next: chrootctl --name {target_name} fix-tty"
        elif post_import == "shell":
            validation_summary = f"{validation_summary}; next: chrootctl --name {target_name} start --login"
    logger.info("imported chroot %s from %s", target_name, archive_path)
    return ChrootImportResult(
        name=target_name,
        archive=archive_path,
        arch=str(manifest.get("arch", getattr(target_config, "target_arch", "arm64"))),
        path=target_config.chroot_base,
        checksum_verified=checksum_verified,
        checksum_path=checksum_path if checksum_path.exists() else None,
        conflict_strategy=conflict,
        encrypted=encrypted,
        validation_ok=validation_ok,
        validation_summary=validation_summary,
        post_import_action=post_import,
    )



def _ensure_openssl() -> str:
    binary = shutil.which("openssl")
    if binary is None:
        raise AppError(
            code="openssl_missing",
            title="OpenSSL is required for encrypted archives",
            message="Install openssl on the host before exporting or importing encrypted transfer archives.",
            hints=["Try: apt install openssl", "Or export without encryption."],
            status_code=400,
        )
    return binary


def _encrypt_archive(archive_path: Path, password: str) -> Path:
    openssl = _ensure_openssl()
    encrypted_path = archive_path.with_suffix(archive_path.suffix + ".enc")
    result = subprocess.run(
        [
            openssl,
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-in",
            str(archive_path),
            "-out",
            str(encrypted_path),
            "-pass",
            f"pass:{password}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to encrypt {archive_path.name}")
    archive_path.unlink(missing_ok=True)
    return encrypted_path


def _decrypt_archive(archive_path: Path, password: str | None, tmpdir: Path) -> Path:
    if not password:
        raise AppError(
            code="transfer_password_required",
            title="Password required",
            message=f"{archive_path.name} is encrypted. Provide the export password to inspect or import it.",
            hints=["Use --password in CLI", "Enter the password in the Web UI import form."],
            status_code=400,
        )
    openssl = _ensure_openssl()
    decrypted_path = tmpdir / archive_path.name.removesuffix(".enc")
    result = subprocess.run(
        [
            openssl,
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-in",
            str(archive_path),
            "-out",
            str(decrypted_path),
            "-pass",
            f"pass:{password}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AppError(
            code="transfer_password_invalid",
            title="Encrypted archive could not be opened",
            message="The supplied password did not decrypt the transfer archive.",
            details={"archive": str(archive_path)},
            hints=["Re-enter the password used during export."],
            status_code=400,
        )
    return decrypted_path

def _directory_size(path: Path) -> int:
    if path.is_file():
        return int(path.stat().st_size)
    total = 0
    if not path.exists():
        return 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return int(total)


def validate_imported_chroot(path: Path, *, arch: str = "") -> dict[str, Any]:
    messages: list[str] = []
    required = ("etc",)
    missing = [name for name in required if not (path / name).exists()]
    if missing:
        messages.append(f"missing required paths: {', '.join(missing)}")
    if not (path / "bin").exists() and not (path / "usr/bin").exists():
        messages.append("executable directories not detected yet")
    if not ((path / "var/lib/dpkg/status").exists() or (path / "var/lib/pacman/local").exists()):
        messages.append("package database not detected yet")
    summary = "Imported chroot looks ready."
    if messages:
        summary = "; ".join(messages)
    if arch and not messages:
        summary = f"Imported chroot looks ready for target arch={arch}."
    return {"ok": not missing, "summary": summary, "missing": tuple(missing), "arch": arch or None, "messages": tuple(messages)}

def _package_inventory(path: Path) -> set[str]:
    status_file = path / "var/lib/dpkg/status"
    if status_file.exists():
        packages: set[str] = set()
        for line in status_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("Package: "):
                packages.add(line.split(": ", 1)[1].strip())
        return packages
    pacman_dir = path / "var/lib/pacman/local"
    if pacman_dir.exists():
        return {child.name.rsplit("-", 2)[0] for child in pacman_dir.iterdir() if child.is_dir()}
    return set()
