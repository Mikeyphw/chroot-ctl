from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import AppError
from ..models import ChrootArchiveInspection, ChrootExportResult, ChrootImportResult, ChrootRecord, ChrootRemovalResult, ChrootRenameResult
from ..registry import ChrootRegistry
from ..system import SystemRunner
from ..validation import validate_chroot_name as _validate_chroot_name
from .storage_safety import (
    best_effort_mutation_state,
    decompress_zstd_to_tar,
    extract_preflighted_tar,
    preflight_tar,
    read_regular_member,
    require_archive_outside_source,
    require_contained,
    require_successful_unmount,
    require_unmounted,
    safe_basename,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_checksum_file(path: Path) -> str:
    line = path.read_text(encoding="utf-8").strip().splitlines()[0]
    return line.split()[0].strip()


def validate_chroot_name(name: str) -> str:
    try:
        return _validate_chroot_name(name)
    except ValueError as exc:
        message = str(exc)
        if "is required" in message:
            message = "new chroot name is required"
        elif "invalid chroot name" not in message:
            message = f"invalid chroot name: {name!r}"
        raise RuntimeError(message) from exc


def _next_available_name(name: str, registry: ChrootRegistry, config) -> str:
    counter = 2
    candidate = name
    while registry.get(candidate) is not None or config.for_chroot(candidate).chroot_base.exists():
        candidate = f"{name}-{counter}"
        counter += 1
    return candidate


def record_from_registry(row: dict[str, object]) -> ChrootRecord:
    metadata = row.get("metadata", {})
    return ChrootRecord(
        name=str(row.get("name", "")),
        distro=str(row.get("distro", "")),
        path=str(row.get("path", "")),
        arch=str(row.get("arch", "")),
        release_name=str(row.get("release_name", "")),
        version=str(row.get("version", "")),
        phase=str(row.get("phase", "")),
        installed=bool(row.get("installed")),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
        metadata={str(key): str(value) for key, value in metadata.items()} if isinstance(metadata, dict) else {},
    )


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
    unmount_result = require_successful_unmount(controller, name=name)
    target_path = require_contained(target_config.chroot_root, Path(str(record["path"])), label="registered chroot path")
    if runner.dry_run:
        return ChrootRemovalResult(name=name, removed=False, unmounted_success=unmount_result.success, unmounted_failed=unmount_result.failed)

    mutation_id = registry.begin_fs_mutation(kind="chroot.remove", target=name, source_path=str(target_path))
    trash = target_config.chroot_root / f".chrootctl-remove-{name}-{uuid.uuid4().hex}"
    moved = False
    try:
        if target_path.exists():
            os.replace(target_path, trash)
            moved = True
            registry.update_fs_mutation(mutation_id, "staged", detail={"trash": str(trash)})
        try:
            registry.delete(name)
        except Exception:
            if moved and trash.exists() and not target_path.exists():
                os.replace(trash, target_path)
            raise
    except Exception as exc:
        best_effort_mutation_state(registry, mutation_id, "rolled_back", logger, detail={"error": str(exc)})
        raise

    # Registry deletion is the authoritative commit point. Journal finalization and
    # old-tree cleanup must never attempt to roll back a committed removal.
    best_effort_mutation_state(
        registry, mutation_id, "promoting", logger, detail={"trash": str(trash) if moved else ""}
    )
    cleanup_error = ""
    if moved and trash.exists():
        try:
            shutil.rmtree(trash)
        except OSError as exc:
            cleanup_error = str(exc)
    best_effort_mutation_state(
        registry,
        mutation_id,
        "complete",
        logger,
        detail={"trash_cleanup_error": cleanup_error} if cleanup_error else {},
    )
    return ChrootRemovalResult(name=name, removed=True, unmounted_success=unmount_result.success, unmounted_failed=unmount_result.failed)


def rename_chroot(config, registry: ChrootRegistry, runner, logger: Any, old_name: str, new_name: str) -> ChrootRenameResult:
    normalized_new_name = validate_chroot_name(new_name)
    record = registry.get(old_name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {old_name}")
    if registry.get(normalized_new_name) is not None:
        raise RuntimeError(f"destination chroot already exists: {normalized_new_name}")
    old_config = config.for_chroot(old_name)
    new_config = config.for_chroot(normalized_new_name)
    registry_path = require_contained(old_config.chroot_root, Path(str(record["path"])), label="registered chroot path")
    new_path = require_contained(new_config.chroot_root, new_config.chroot_base, label="rename destination path")
    if new_path.exists():
        raise RuntimeError(f"destination path already exists: {new_path}")
    from ..controller import ChrootController

    controller = ChrootController(old_config, runner, logger)
    require_successful_unmount(controller, name=old_name)
    mutation_id = registry.begin_fs_mutation(
        kind="chroot.rename",
        target=old_name,
        source_path=str(registry_path),
        destination_path=str(new_path),
        detail={"new_name": normalized_new_name},
    )
    moved = False
    try:
        if registry_path.exists():
            os.replace(registry_path, new_path)
            moved = True
            registry.update_fs_mutation(mutation_id, "staged")
        registry.rename(old_name, normalized_new_name, new_path=str(new_path))
    except Exception as exc:
        if moved and new_path.exists() and not registry_path.exists():
            os.replace(new_path, registry_path)
        best_effort_mutation_state(registry, mutation_id, "rolled_back", logger, detail={"error": str(exc)})
        raise
    # The registry rename and filesystem move now agree; journal bookkeeping is non-authoritative.
    best_effort_mutation_state(
        registry, mutation_id, "complete", logger, detail={"new_name": normalized_new_name}
    )
    return ChrootRenameResult(old_name=old_name, new_name=normalized_new_name, renamed=True)


def _tar_with_zstd_args(*, create: bool, archive: Path, cwd: Path, members: list[str]) -> list[str]:
    del cwd
    base = ["tar", "--zstd", "-cpf" if create else "-xpf", str(archive)]
    return [*base, *members]


def _tar_zstd_env() -> dict[str, str]:
    env = os.environ.copy()
    candidates = [
        shutil.which("zstd"),
        "/data/data/com.termux/files/usr/bin/zstd",
        "/data/user/0/com.termux/files/usr/bin/zstd",
        "/system/bin/zstd",
        "/usr/bin/zstd",
        "/bin/zstd",
    ]
    zstd = next((Path(candidate) for candidate in candidates if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK)), None)
    if zstd is None:
        raise RuntimeError("zstd command not found. Install zstd on the host (Termux: pkg install zstd) or provide it in PATH.")
    env["PATH"] = f"{zstd.parent}:{env.get('PATH', '')}"
    return env


def _safe_archive_tar(archive: Path, *, password: str | None, tmpdir: Path, runner) -> tuple[Path, list[Any], int]:
    source_archive = archive
    if archive.name.endswith(".enc"):
        source_archive = _decrypt_archive(archive, password, tmpdir, runner)
    tar_path = tmpdir / "archive.tar"
    decompress_zstd_to_tar(source_archive, tar_path, runner=runner)
    members, extracted_size = preflight_tar(tar_path)
    return tar_path, members, extracted_size


def _read_export_manifest(archive: Path, *, password: str | None = None, runner) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="chrootctl-import-manifest-") as tmp:
        tmpdir = Path(tmp)
        tar_path, _members, _extracted_size = _safe_archive_tar(archive, password=password, tmpdir=tmpdir, runner=runner)
        raw = read_regular_member(tar_path, ".chrootctl-export.json")
        manifest = json.loads(raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise RuntimeError("archive manifest must be a JSON object")
        path_name = safe_basename(str(manifest.get("path_name") or manifest.get("name") or ""), label="manifest path_name")
        validate_chroot_name(path_name)
        manifest["path_name"] = path_name
        return manifest


def inspect_chroot_archive(archive: Path, *, registry: ChrootRegistry | None = None, password: str | None = None, runner=None) -> ChrootArchiveInspection:
    runner = runner or SystemRunner(logging.getLogger("chrootctl.archive"), dry_run=False)
    archive_path = archive.expanduser().resolve()
    if not archive_path.exists():
        raise RuntimeError(f"archive does not exist: {archive_path}")
    encrypted = archive_path.name.endswith(".enc")
    with tempfile.TemporaryDirectory(prefix="chrootctl-import-inspect-") as tmp:
        tmpdir = Path(tmp)
        tar_path, _members, extracted_size = _safe_archive_tar(archive_path, password=password, tmpdir=tmpdir, runner=runner)
        raw = read_regular_member(tar_path, ".chrootctl-export.json")
        manifest = json.loads(raw.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("archive manifest must be a JSON object")
    path_name = safe_basename(str(manifest.get("path_name") or manifest.get("name") or ""), label="manifest path_name")
    validate_chroot_name(path_name)
    source_name = validate_chroot_name(str(manifest.get("name") or path_name or archive_path.stem.replace(".tar", "")))
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
        path_name=path_name,
        distro=str(manifest.get("distro", "")),
        arch=str(manifest.get("arch", "")),
        release_name=str(manifest.get("release_name", "")),
        version=str(manifest.get("version", "")),
        phase=str(manifest.get("phase", "")),
        installed=bool(manifest.get("installed")),
        metadata=dict(manifest.get("metadata", {})),
        size_bytes=archive_path.stat().st_size,
        extracted_size_bytes=extracted_size,
        created_at=created_at,
        checksum=checksum,
        checksum_path=checksum_path if checksum_path.exists() else None,
        checksum_verified=checksum_verified,
        encrypted=encrypted,
        target_exists=target_exists,
    )


def _exclusive_manifest(path: Path, payload: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def export_chroot(config, registry: ChrootRegistry, runner, logger: Any, name: str, *, archive: Path | None = None, password: str | None = None) -> ChrootExportResult:
    record = registry.get(name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {name}")
    target_config = config.for_chroot(name)
    chroot_path = require_contained(target_config.chroot_root, Path(str(record["path"])), label="registered chroot path")
    if not chroot_path.exists():
        raise RuntimeError(f"chroot path does not exist: {chroot_path}")
    from ..controller import ChrootController

    require_unmounted(ChrootController(target_config, runner, logger), name=name)
    requested = (archive or Path.cwd() / f"{name}.tar.zst").expanduser().resolve()
    if password and requested.name.endswith(".enc"):
        base_archive = requested.with_name(requested.name.removesuffix(".enc"))
        final_archive = requested
    else:
        base_archive = requested
        final_archive = requested.with_suffix(requested.suffix + ".enc") if password else requested
    require_archive_outside_source(chroot_path, final_archive)
    final_archive.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "distro": str(record.get("distro", "")),
        "arch": str(record.get("arch") or getattr(target_config, "target_arch", "arm64")),
        "release_name": str(record.get("release_name", "")),
        "version": str(record.get("version", "")),
        "phase": str(record.get("phase", "")),
        "installed": bool(record.get("installed")),
        "metadata": record.get("metadata", {}),
        "path_name": safe_basename(chroot_path.name, label="chroot directory name"),
    }
    manifest_path = chroot_path.parent / ".chrootctl-export.json"
    temp_base = final_archive.parent / f".{base_archive.name}.partial-{uuid.uuid4().hex}"
    temp_result = temp_base
    _exclusive_manifest(manifest_path, manifest)
    try:
        result = runner.run(
            ["tar", "--zstd", "-cpf", str(temp_base), "-C", str(chroot_path.parent), chroot_path.name, manifest_path.name],
            check=False,
            env=_tar_zstd_env(),
            max_capture_bytes=256 * 1024,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to export {name} to {final_archive}")
        if password:
            temp_result = _encrypt_archive(temp_base, password, runner)
        os.replace(temp_result, final_archive)
    finally:
        manifest_path.unlink(missing_ok=True)
        temp_base.unlink(missing_ok=True)
        temp_base.with_suffix(temp_base.suffix + ".enc").unlink(missing_ok=True)
    checksum = _sha256_file(final_archive)
    checksum_path = final_archive.with_name(f"{final_archive.name}.sha256")
    checksum_tmp = checksum_path.with_name(f".{checksum_path.name}.partial-{uuid.uuid4().hex}")
    checksum_tmp.write_text(f"{checksum}  {final_archive.name}\n", encoding="utf-8")
    os.replace(checksum_tmp, checksum_path)
    logger.info("exported chroot %s to %s", name, final_archive)
    return ChrootExportResult(name=name, archive=final_archive, arch=str(manifest["arch"]), checksum=checksum, checksum_path=checksum_path, encrypted=bool(password))


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
    if conflict not in {"rename", "overwrite"}:
        raise RuntimeError(f"unsupported conflict strategy: {conflict}")
    if post_import not in {"register", "validate", "fixups", "shell"}:
        raise RuntimeError(f"unsupported post-import action: {post_import}")
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    checksum_verified = None
    if checksum_path.exists():
        checksum_verified = _read_checksum_file(checksum_path) == _sha256_file(archive_path)
        if not checksum_verified:
            raise RuntimeError(f"checksum verification failed for {archive_path.name}")

    manifest = _read_export_manifest(archive_path, password=password, runner=runner)
    path_name = safe_basename(str(manifest["path_name"]), label="manifest path_name")
    source_name = validate_chroot_name(str(manifest.get("name") or path_name))
    requested_name = validate_chroot_name(name or source_name)
    target_name = requested_name
    existing_record = registry.get(target_name)
    target_config = config.for_chroot(target_name)
    if existing_record is not None or target_config.chroot_base.exists():
        if conflict == "rename":
            target_name = _next_available_name(requested_name, registry, config)
            target_config = config.for_chroot(target_name)
            existing_record = None
    target_path = (
        require_contained(target_config.chroot_root, Path(str(existing_record["path"])), label="existing registered chroot path")
        if existing_record is not None
        else require_contained(target_config.chroot_root, target_config.chroot_base, label="import target path")
    )
    target_config.chroot_root.mkdir(parents=True, exist_ok=True)
    mutation_id = registry.begin_fs_mutation(
        kind="chroot.import",
        target=target_name,
        source_path=str(archive_path),
        destination_path=str(target_path),
        detail={"conflict": conflict, "had_existing": existing_record is not None},
    )
    backup_path = target_config.chroot_root / f".chrootctl-backup-{target_name}-{uuid.uuid4().hex}"
    promoted = False
    backed_up = False
    try:
        with tempfile.TemporaryDirectory(prefix=".chrootctl-import-", dir=target_config.chroot_root) as tmp:
            tmpdir = Path(tmp)
            tar_path, members, extracted_size = _safe_archive_tar(archive_path, password=password, tmpdir=tmpdir, runner=runner)
            reserve = 64 * 1024 * 1024
            if shutil.disk_usage(tmpdir).free < int(extracted_size) + reserve:
                raise RuntimeError("insufficient free space for preflighted archive extraction")
            extract_root = tmpdir / "extract"
            extract_preflighted_tar(tar_path, extract_root, members)
            extracted_path = require_contained(extract_root, extract_root / path_name, label="extracted chroot path")
            if not extracted_path.is_dir():
                raise RuntimeError(f"archive is missing extracted chroot directory: {path_name}")
            staged_path = target_config.chroot_root / f".chrootctl-stage-{target_name}-{uuid.uuid4().hex}"
            os.replace(extracted_path, staged_path)
            registry.update_fs_mutation(mutation_id, "staged", detail={"staged_path": str(staged_path)})
            try:
                if target_path.exists():
                    os.replace(target_path, backup_path)
                    backed_up = True
                registry.update_fs_mutation(mutation_id, "promoting", detail={"backup_path": str(backup_path) if backed_up else ""})
                os.replace(staged_path, target_path)
                promoted = True
                imported_metadata = dict(manifest.get("metadata", {}))
                imported_metadata["_chrootctl_mutation_id"] = mutation_id
                registry.upsert(
                    name=target_name,
                    distro=str(manifest.get("distro", "")),
                    path=str(target_path),
                    arch=str(manifest.get("arch", getattr(target_config, "target_arch", "arm64"))),
                    release_name=str(manifest.get("release_name", "")),
                    version=str(manifest.get("version", "")),
                    phase=str(manifest.get("phase", "extract") or "extract"),
                    installed=bool(manifest.get("installed")),
                    metadata=imported_metadata,
                )
            except Exception:
                if promoted and target_path.exists():
                    shutil.rmtree(target_path)
                if backed_up and backup_path.exists():
                    os.replace(backup_path, target_path)
                raise
            finally:
                if staged_path.exists():
                    shutil.rmtree(staged_path)
    except Exception as exc:
        best_effort_mutation_state(registry, mutation_id, "rolled_back", logger, detail={"error": str(exc)})
        raise

    # Registry upsert is the authoritative commit point. Removing the rollback copy
    # and finalizing the mutation journal are best-effort post-commit cleanup.
    backup_cleanup_error = ""
    if backup_path.exists():
        try:
            shutil.rmtree(backup_path)
        except OSError as cleanup_exc:
            backup_cleanup_error = str(cleanup_exc)
    best_effort_mutation_state(
        registry,
        mutation_id,
        "complete",
        logger,
        detail={"backup_cleanup_error": backup_cleanup_error} if backup_cleanup_error else {},
    )

    validation_ok = None
    validation_summary = ""
    if post_import in {"validate", "fixups", "shell"}:
        validation = validate_imported_chroot(target_path, arch=str(manifest.get("arch", getattr(target_config, "target_arch", "arm64"))))
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
        path=target_path,
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


def _openssl_password_stdin(password: str) -> str:
    if "\n" in password or "\r" in password or "\x00" in password:
        raise RuntimeError("transfer password must not contain newline or NUL characters")
    return f"{password}\n"


def _encrypt_archive(archive_path: Path, password: str, runner) -> Path:
    openssl = _ensure_openssl()
    encrypted_path = archive_path.with_suffix(archive_path.suffix + ".enc")
    result = runner.run(
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
            "stdin",
        ],
        check=False,
        input_text=_openssl_password_stdin(password),
        max_capture_bytes=256 * 1024,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to encrypt {archive_path.name}")
    archive_path.unlink(missing_ok=True)
    return encrypted_path


def _decrypt_archive(archive_path: Path, password: str | None, tmpdir: Path, runner) -> Path:
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
    result = runner.run(
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
            "stdin",
        ],
        check=False,
        input_text=_openssl_password_stdin(password),
        max_capture_bytes=256 * 1024,
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
