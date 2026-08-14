from __future__ import annotations

import glob
import os
import posixpath
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


def contains_path(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def require_contained(root: Path, candidate: Path, *, label: str) -> Path:
    resolved = candidate.expanduser().resolve(strict=False)
    if not contains_path(root, resolved):
        raise RuntimeError(f"{label} is outside managed root: {resolved}")
    return resolved


def safe_basename(value: str, *, label: str) -> str:
    name = str(value or "").strip()
    if not name or name in {".", ".."}:
        raise RuntimeError(f"{label} is required")
    if Path(name).name != name or "/" in name or "\\" in name or "\x00" in name:
        raise RuntimeError(f"unsafe {label}: {value!r}")
    return name


def require_archive_outside_source(source: Path, archive: Path) -> Path:
    source_resolved = source.resolve(strict=False)
    archive_resolved = archive.expanduser().resolve(strict=False)
    if contains_path(source_resolved, archive_resolved):
        raise RuntimeError(f"archive destination must not be inside source tree: {archive_resolved}")
    return archive_resolved


def require_unmounted(controller, *, name: str) -> None:
    rows = controller.status(verbose=True)
    mounted = [row for row in rows if str(row.get("mounted", "")).lower() == "yes"]
    if mounted:
        targets = ", ".join(str(row.get("target") or row.get("path") or "mounted path") for row in mounted[:5])
        raise RuntimeError(f"{name} must be fully unmounted before this operation; mounted: {targets}")


def require_successful_unmount(controller, *, name: str):
    result = controller.unmount()
    if result.failed:
        detail = "; ".join(result.errors) or f"{result.failed} mount(s) failed to unmount"
        raise RuntimeError(f"failed to unmount {name}: {detail}")
    require_unmounted(controller, name=name)
    return result




def best_effort_mutation_state(registry, mutation_id: str, state: str, logger, *, detail: dict | None = None) -> None:
    """Record mutation-journal state without allowing bookkeeping to corrupt committed data."""
    try:
        registry.update_fs_mutation(mutation_id, state, detail=detail or {})
    except Exception as exc:
        try:
            logger.warning("failed to update filesystem mutation %s to %s: %s", mutation_id, state, exc)
        except Exception:
            pass


def _recovery_path(root: Path, value: Any, *, label: str) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return require_contained(root, Path(text), label=label)


def _quarantine_recovery_path(root: Path, path: Path | None, *, mutation_id: str, label: str) -> Path | None:
    if path is None or not path.exists():
        return None
    safe_tail = safe_basename(path.name, label=f"{label} basename")
    prefix = f".chrootctl-recovery-{mutation_id[:12]}-{safe_tail}"
    candidate = require_contained(root, root / prefix, label=f"{label} quarantine")
    counter = 2
    while candidate.exists():
        candidate = require_contained(root, root / f"{prefix}-{counter}", label=f"{label} quarantine")
        counter += 1
    os.replace(path, candidate)
    return candidate


def _single_recovery_candidate(directory: Path, pattern: str, *, label: str) -> Path | None:
    matches = sorted(path for path in directory.glob(pattern) if path.exists())
    if not matches:
        return None
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous {label}: found {len(matches)} candidates")
    return matches[0]


def recover_pending_fs_mutations(services) -> list[dict[str, Any]]:
    """Conservatively reconcile interrupted filesystem/registry transactions.

    Recovery never deletes ambiguous data.  Trees that cannot be proven to be
    either the authoritative old or new generation are moved to a managed
    recovery quarantine and recorded in the mutation journal for manual review.
    """
    if services.dry_run:
        return []
    registry = services.registry
    logger = services.logger
    root = services.base_config.chroot_root.expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for row in registry.pending_fs_mutations(limit=200):
        mutation_id = str(row.get("mutation_id") or "")
        kind = str(row.get("kind") or "")
        target = str(row.get("target") or "")
        state = str(row.get("state") or "")
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        if detail.get("_corrupt"):
            best_effort_mutation_state(registry, mutation_id, "blocked", logger, detail={"recovery_error": "corrupt mutation detail"})
            results.append({"mutationId": mutation_id, "kind": kind, "state": "blocked"})
            continue

        try:
            # Import source archives may intentionally live outside the managed
            # chroot root; they are read-only inputs and are never recovery targets.
            source = None if kind == "chroot.import" else _recovery_path(root, row.get("source_path"), label="mutation source")
            destination = _recovery_path(root, row.get("destination_path"), label="mutation destination")
            stage = _recovery_path(root, detail.get("stage") or detail.get("staged_path"), label="mutation stage")
            backup = _recovery_path(root, detail.get("backup") or detail.get("backup_path"), label="mutation backup")
            trash = _recovery_path(root, detail.get("trash"), label="mutation trash")
            if kind == "chroot.remove" and trash is None and target:
                trash = _single_recovery_candidate(root, f".chrootctl-remove-{glob.escape(target)}-*", label="remove trash")
            elif kind == "chroot.import" and target:
                if stage is None:
                    stage = _single_recovery_candidate(root, f".chrootctl-stage-{glob.escape(target)}-*", label="import stage")
                if backup is None:
                    backup = _single_recovery_candidate(root, f".chrootctl-backup-{glob.escape(target)}-*", label="import backup")
            elif kind == "snapshot.restore" and target:
                if stage is None:
                    stage = _single_recovery_candidate(root, f".chrootctl-restore-stage-{glob.escape(target)}-*", label="restore stage")
                if backup is None:
                    backup = _single_recovery_candidate(root, f".chrootctl-restore-backup-{glob.escape(target)}-*", label="restore backup")
            elif kind == "snapshot.create" and destination is not None and stage is None:
                snapshot_name = str(detail.get("snapshot") or "")
                if snapshot_name:
                    stage = _single_recovery_candidate(destination.parent, f".partial-{glob.escape(snapshot_name)}-*", label="snapshot stage")
            elif kind == "install.extract" and target:
                if source is None:
                    source = _single_recovery_candidate(root, f".chrootctl-install-rootfs-*", label="install stage")
                if backup is None and destination is not None:
                    backup = _single_recovery_candidate(destination.parent, f".{glob.escape(destination.name)}.preinstall-*", label="install backup")
            recovered_state = "blocked"
            recovery_detail: dict[str, Any] = {"recovered_from": state}

            if kind == "chroot.remove":
                record = registry.get(target)
                if record is not None:
                    if source is not None and source.exists():
                        quarantined = _quarantine_recovery_path(root, trash, mutation_id=mutation_id, label="remove trash")
                        if quarantined is not None:
                            recovery_detail["quarantine"] = str(quarantined)
                        recovered_state = "rolled_back"
                    elif source is not None and trash is not None and trash.exists():
                        os.replace(trash, source)
                        recovered_state = "rolled_back"
                    else:
                        recovery_detail["recovery_error"] = "registry row exists but neither source nor staged trash can restore it"
                else:
                    quarantined = _quarantine_recovery_path(root, trash, mutation_id=mutation_id, label="committed removal")
                    if quarantined is not None:
                        recovery_detail["quarantine"] = str(quarantined)
                    if source is None or not source.exists():
                        recovered_state = "complete"
                    else:
                        recovery_detail["recovery_error"] = "registry row was removed but original source path still exists"

            elif kind == "chroot.rename":
                old_record = registry.get(target)
                destination_record = registry.find_by_path(str(destination)) if destination is not None else None
                if old_record is None and destination_record is not None and destination is not None and destination.exists():
                    recovered_state = "complete"
                elif old_record is not None and source is not None:
                    if source.exists() and (destination is None or not destination.exists()):
                        recovered_state = "rolled_back"
                    elif not source.exists() and destination is not None and destination.exists():
                        os.replace(destination, source)
                        recovered_state = "rolled_back"
                    elif source.exists() and destination is not None and destination.exists():
                        quarantined = _quarantine_recovery_path(root, destination, mutation_id=mutation_id, label="rename destination")
                        if quarantined is not None:
                            recovery_detail["quarantine"] = str(quarantined)
                        recovered_state = "rolled_back"
                    else:
                        recovery_detail["recovery_error"] = "rename source and destination are both unavailable"
                else:
                    recovery_detail["recovery_error"] = "rename registry state does not identify a committed generation"

            elif kind == "chroot.import":
                record = registry.get(target)
                metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
                committed = isinstance(metadata, dict) and metadata.get("_chrootctl_mutation_id") == mutation_id
                if committed and destination is not None and destination.exists():
                    for candidate, label in ((stage, "import stage"), (backup, "import backup")):
                        quarantined = _quarantine_recovery_path(root, candidate, mutation_id=mutation_id, label=label)
                        if quarantined is not None:
                            recovery_detail.setdefault("quarantine", []).append(str(quarantined))
                    recovered_state = "complete"
                else:
                    had_existing = bool(detail.get("had_existing"))
                    if backup is not None and backup.exists() and destination is not None:
                        if destination.exists():
                            quarantined = _quarantine_recovery_path(root, destination, mutation_id=mutation_id, label="uncommitted import")
                            if quarantined is not None:
                                recovery_detail.setdefault("quarantine", []).append(str(quarantined))
                        os.replace(backup, destination)
                    elif not had_existing and destination is not None and destination.exists():
                        quarantined = _quarantine_recovery_path(root, destination, mutation_id=mutation_id, label="uncommitted import")
                        if quarantined is not None:
                            recovery_detail.setdefault("quarantine", []).append(str(quarantined))
                    quarantined_stage = _quarantine_recovery_path(root, stage, mutation_id=mutation_id, label="import stage")
                    if quarantined_stage is not None:
                        recovery_detail.setdefault("quarantine", []).append(str(quarantined_stage))
                    recovered_state = "rolled_back"


            elif kind == "install.extract":
                record = registry.get(target)
                metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
                committed = isinstance(metadata, dict) and metadata.get("_chrootctl_install_mutation_id") == mutation_id
                if committed and destination is not None and destination.exists():
                    for candidate, label in ((source, "install stage"), (backup, "install backup")):
                        quarantined = _quarantine_recovery_path(root, candidate, mutation_id=mutation_id, label=label)
                        if quarantined is not None:
                            recovery_detail.setdefault("quarantine", []).append(str(quarantined))
                    recovered_state = "complete"
                else:
                    # Without the durable registry marker, prefer the previous
                    # generation and preserve any promoted/staged candidate in
                    # quarantine for manual inspection rather than deleting it.
                    if backup is not None and backup.exists() and destination is not None:
                        if destination.exists():
                            quarantined = _quarantine_recovery_path(root, destination, mutation_id=mutation_id, label="uncommitted install")
                            if quarantined is not None:
                                recovery_detail.setdefault("quarantine", []).append(str(quarantined))
                        os.replace(backup, destination)
                    elif not bool(detail.get("had_existing")) and destination is not None and destination.exists():
                        quarantined = _quarantine_recovery_path(root, destination, mutation_id=mutation_id, label="uncommitted install")
                        if quarantined is not None:
                            recovery_detail.setdefault("quarantine", []).append(str(quarantined))
                    quarantined_stage = _quarantine_recovery_path(root, source, mutation_id=mutation_id, label="install stage")
                    if quarantined_stage is not None:
                        recovery_detail.setdefault("quarantine", []).append(str(quarantined_stage))
                    recovered_state = "rolled_back"

            elif kind == "snapshot.create":
                snapshot_name = str(detail.get("snapshot") or "")
                committed = False
                if snapshot_name:
                    try:
                        snapshot = registry.get_snapshot_by_name(target, snapshot_name)
                        committed = snapshot.metadata.get("_chrootctl_mutation_id") == mutation_id
                    except KeyError:
                        committed = False
                if committed and destination is not None and destination.exists():
                    recovered_state = "complete"
                else:
                    for candidate, label in ((stage, "snapshot stage"), (destination, "uncommitted snapshot")):
                        quarantined = _quarantine_recovery_path(root, candidate, mutation_id=mutation_id, label=label)
                        if quarantined is not None:
                            recovery_detail.setdefault("quarantine", []).append(str(quarantined))
                    recovered_state = "rolled_back"

            elif kind == "snapshot.restore":
                # Restore has no registry-row mutation.  `stage` disappearing after
                # state=promoting is the durable signal that os.replace(stage,target)
                # completed; otherwise restore the backup and quarantine the stage.
                promoted = state in {"promoting", "committed"} and destination is not None and destination.exists() and (stage is None or not stage.exists())
                if promoted:
                    quarantined = _quarantine_recovery_path(root, backup, mutation_id=mutation_id, label="restore backup")
                    if quarantined is not None:
                        recovery_detail["quarantine"] = str(quarantined)
                    recovered_state = "complete"
                else:
                    if destination is not None and not destination.exists() and backup is not None and backup.exists():
                        os.replace(backup, destination)
                    quarantined = _quarantine_recovery_path(root, stage, mutation_id=mutation_id, label="restore stage")
                    if quarantined is not None:
                        recovery_detail["quarantine"] = str(quarantined)
                    recovered_state = "rolled_back"

            else:
                recovery_detail["recovery_error"] = f"unsupported mutation kind: {kind}"

            best_effort_mutation_state(registry, mutation_id, recovered_state, logger, detail=recovery_detail)
            results.append({"mutationId": mutation_id, "kind": kind, "state": recovered_state, **recovery_detail})
        except Exception as exc:
            best_effort_mutation_state(registry, mutation_id, "blocked", logger, detail={"recovery_error": str(exc), "recovered_from": state})
            logger.warning("filesystem mutation recovery blocked for %s (%s): %s", mutation_id, kind, exc)
            results.append({"mutationId": mutation_id, "kind": kind, "state": "blocked", "error": str(exc)})

    return results


def _zstd_binary() -> str:
    candidates = (
        shutil.which("zstd"),
        "/data/data/com.termux/files/usr/bin/zstd",
        "/data/user/0/com.termux/files/usr/bin/zstd",
        "/system/bin/zstd",
        "/usr/bin/zstd",
        "/bin/zstd",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise RuntimeError("zstd command not found; install zstd before importing archives")


def decompress_zstd_to_tar(source: Path, destination: Path, *, runner) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    reserve = 64 * 1024 * 1024
    free_bytes = shutil.disk_usage(destination.parent).free
    max_bytes = max(int(free_bytes) - reserve, 0)
    if max_bytes <= 0:
        raise RuntimeError("insufficient free space to stage decompressed archive")
    try:
        result = runner.run(
            [_zstd_binary(), "-d", "-f", "-o", str(destination), "--", str(source)],
            check=False,
            max_capture_bytes=256 * 1024,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed to decompress archive: {source}")
        if not destination.is_file():
            raise RuntimeError(f"zstd did not produce the staged TAR: {destination}")
        if destination.stat().st_size > max_bytes:
            raise RuntimeError("decompressed archive exceeds safe staging capacity")
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _parts_safe(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _normalize_archive_link(member: tarfile.TarInfo) -> None:
    target = PurePosixPath(member.linkname)
    if not target.is_absolute():
        return
    parts = PurePosixPath(member.name).parts
    if not parts:
        raise RuntimeError(f"unsafe archive link member: {member.name!r}")
    archive_root_target = PurePosixPath(parts[0], *target.parts[1:])
    if member.issym():
        member.linkname = posixpath.relpath(str(archive_root_target), str(PurePosixPath(member.name).parent))
    else:
        member.linkname = str(archive_root_target)


def _link_target_safe(member: tarfile.TarInfo) -> bool:
    _normalize_archive_link(member)
    target = PurePosixPath(member.linkname)
    if target.is_absolute():
        return False
    if member.issym():
        combined = PurePosixPath(member.name).parent / target
    else:
        combined = target
    normalized: list[str] = []
    for part in combined.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not normalized:
                return False
            normalized.pop()
        else:
            normalized.append(part)
    member_parts = PurePosixPath(member.name).parts
    # A link inside a top-level archive tree must remain inside that same tree
    # after the tree is atomically promoted out of the extraction staging root.
    return bool(normalized and member_parts and normalized[0] == member_parts[0])


def preflight_tar(tar_path: Path) -> tuple[list[tarfile.TarInfo], int]:
    with tarfile.open(tar_path, mode="r:") as handle:
        members = handle.getmembers()
    if not members:
        raise RuntimeError("archive is empty")
    total = 0
    for member in members:
        if not _parts_safe(member.name):
            raise RuntimeError(f"unsafe archive member path: {member.name!r}")
        if member.isdev() or member.isfifo():
            raise RuntimeError(f"unsupported special archive member: {member.name!r}")
        if (member.issym() or member.islnk()) and not _link_target_safe(member):
            raise RuntimeError(f"unsafe archive link target for {member.name!r}: {member.linkname!r}")
        if member.isfile():
            total += max(int(member.size), 0)
    return members, total


def extract_preflighted_tar(tar_path: Path, destination: Path, members: Iterable[tarfile.TarInfo] | None = None) -> None:
    checked = list(members) if members is not None else list(preflight_tar(tar_path)[0])
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, mode="r:") as handle:
        handle.extractall(path=destination, members=checked)
    # A new staging directory plus preflight should keep every realized path contained.
    for item in destination.rglob("*"):
        if not contains_path(destination, item):
            raise RuntimeError(f"archive extraction escaped staging directory: {item}")


def read_regular_member(tar_path: Path, member_name: str) -> bytes:
    safe_name = safe_basename(member_name, label="archive member")
    with tarfile.open(tar_path, mode="r:") as handle:
        try:
            member = handle.getmember(safe_name)
        except KeyError as exc:
            raise RuntimeError(f"archive is missing {safe_name}") from exc
        if not member.isfile():
            raise RuntimeError(f"archive member is not a regular file: {safe_name}")
        stream = handle.extractfile(member)
        if stream is None:
            raise RuntimeError(f"unable to read archive member: {safe_name}")
        return stream.read()
