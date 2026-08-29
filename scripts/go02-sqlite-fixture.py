#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chrootctl.registry import ChrootRegistry  # noqa: E402


def _pragmas(registry: ChrootRegistry) -> dict[str, object]:
    with registry.connect() as conn:
        return {
            "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            "synchronous": int(conn.execute("PRAGMA synchronous").fetchone()[0]),
            "busy_timeout": int(conn.execute("PRAGMA busy_timeout").fetchone()[0]),
            "foreign_keys": int(conn.execute("PRAGMA foreign_keys").fetchone()[0]),
            "integrity_check": str(conn.execute("PRAGMA integrity_check").fetchone()[0]),
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        }


def _require_pragmas(registry: ChrootRegistry) -> dict[str, object]:
    values = _pragmas(registry)
    expected = {
        "journal_mode": "wal",
        "synchronous": 2,
        "busy_timeout": 5000,
        "foreign_keys": 1,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
    }
    if values != expected:
        raise RuntimeError(f"SQLite PRAGMA/integrity mismatch: {values!r} != {expected!r}")
    return values


def create_fixture(path: Path) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        candidate.unlink(missing_ok=True)
    registry = ChrootRegistry(path)
    registry.upsert(
        name="python-seed",
        distro="ubuntu",
        path="/data/local/tmp/python-seed",
        phase="ready",
        installed=True,
        arch="arm64",
        release_name="noble",
        version="24.04",
        metadata={"writer": "python", "roundTrip": True},
    )
    registry.add_snapshot(
        name="python-snapshot",
        chroot_name="python-seed",
        path="/data/adb/chrootctl/snapshots/python-seed",
        note="seed",
        size_bytes=7,
        metadata={"writer": "python"},
    )
    mutation_id = registry.begin_fs_mutation(
        kind="seed",
        target="python-seed",
        source_path="/seed/source",
        destination_path="/seed/destination",
        detail={"writer": "python"},
    )
    registry.update_fs_mutation(mutation_id, "verified", detail={"roundTrip": True})
    artifact = registry.register_artifact(
        path="/data/adb/chrootctl/python-artifact",
        kind="fixture",
        target="python-seed",
        size_bytes=7,
        ttl_seconds=None,
        metadata={"writer": "python", "roundTrip": True},
    )
    event = registry.add_event(
        event_type="go02.sqlite.seed",
        actor="python",
        target="python-seed",
        message="Python created the GO02 compatibility database",
        metadata={"writer": "python", "roundTrip": True},
    )
    pragmas = _require_pragmas(registry)
    return {
        "schemaVersion": 1,
        "db": str(path),
        "mutationId": mutation_id,
        "artifactId": artifact["artifact_id"],
        "eventId": event.event_id,
        "pragmas": pragmas,
    }


def verify_round_trip(path: Path) -> dict[str, object]:
    registry = ChrootRegistry(path)
    pragmas = _require_pragmas(registry)
    if registry.get("python-seed") is not None:
        raise RuntimeError("old Python chroot name survived Go rename")
    chroot = registry.get("go-renamed")
    if chroot is None:
        raise RuntimeError("Go-renamed chroot is missing")
    if chroot["path"] != "/data/local/tmp/go-renamed" or chroot["phase"] != "go02-mutated":
        raise RuntimeError(f"Go chroot mutation did not round-trip: {chroot!r}")
    if chroot["metadata"] != {"owner": "go", "source": "python"}:
        raise RuntimeError(f"Go chroot JSON did not round-trip: {chroot['metadata']!r}")

    snapshot = registry.get_snapshot_by_name("go-renamed", "python-snapshot")
    if snapshot.chroot_name != "go-renamed":
        raise RuntimeError("snapshot did not follow ON UPDATE CASCADE")
    python_artifact = registry.artifact_by_path("/data/adb/chrootctl/python-artifact")
    go_artifact = registry.artifact_by_path("/data/adb/chrootctl/go02-artifact")
    if python_artifact is None or python_artifact["metadata"].get("writer") != "python":
        raise RuntimeError("Python artifact was not preserved")
    if go_artifact is None or go_artifact["metadata"] != {"roundTrip": True, "writer": "go"}:
        raise RuntimeError(f"Go artifact did not round-trip through Python: {go_artifact!r}")

    with registry.connect() as conn:
        go_event = conn.execute(
            "SELECT metadata_json FROM events WHERE event_type = ? AND actor = ?",
            ("go02.sqlite.mutate", "go"),
        ).fetchone()
        if go_event is None or json.loads(go_event[0]) != {"roundTrip": True, "writer": "go"}:
            raise RuntimeError("Go audit event is missing or malformed")
        go_mutation = conn.execute(
            "SELECT state, detail_json FROM fs_mutations WHERE mutation_id = ?",
            ("go02-mutation",),
        ).fetchone()
        if go_mutation is None or go_mutation[0] != "verified" or json.loads(go_mutation[1]) != {"roundTrip": True, "writer": "go"}:
            raise RuntimeError("Go filesystem mutation is missing or malformed")

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM chroots WHERE name = ?", ("go-renamed",))
            remaining = int(conn.execute("SELECT COUNT(*) FROM snapshots WHERE chroot_name = ?", ("go-renamed",)).fetchone()[0])
            if remaining != 0:
                raise RuntimeError("snapshot did not follow ON DELETE CASCADE")
        finally:
            conn.rollback()

        try:
            conn.execute(
                "INSERT INTO snapshots(name, chroot_name, path) VALUES (?, ?, ?)",
                ("orphan", "missing-chroot", "/tmp/orphan"),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            conn.rollback()
            raise RuntimeError("foreign-key enforcement accepted an orphan snapshot")
        conn.rollback()

    return {
        "schemaVersion": 1,
        "db": str(path),
        "chroot": "go-renamed",
        "snapshot": "python-snapshot",
        "pythonArtifactPreserved": True,
        "goArtifactReadable": True,
        "onUpdateCascade": True,
        "onDeleteCascade": True,
        "pragmas": pragmas,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GO02 Python/Go SQLite compatibility fixture")
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("db", type=Path)
    args = parser.parse_args()
    payload = create_fixture(args.db) if args.mode == "create" else verify_round_trip(args.db)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
