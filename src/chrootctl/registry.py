from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def _safe_json_dict(value: Any, *, field: str) -> dict[str, Any]:
    """Decode persisted JSON without allowing one corrupt row to break registry reads."""
    raw = str(value or "{}")
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {
            "_corrupt": True,
            "_field": field,
        }
    if not isinstance(decoded, dict):
        return {
            "_corrupt": True,
            "_field": field,
        }
    return decoded

SCHEMA = """
CREATE TABLE IF NOT EXISTS chroots (
    name TEXT PRIMARY KEY,
    distro TEXT NOT NULL,
    path TEXT NOT NULL,
    arch TEXT,
    release_name TEXT,
    version TEXT,
    phase TEXT NOT NULL,
    installed INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS chroots_updated_at
AFTER UPDATE ON chroots
FOR EACH ROW
BEGIN
    UPDATE chroots SET updated_at = CURRENT_TIMESTAMP WHERE name = OLD.name;
END;


CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    chroot_name TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'copy',
    note TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chroot_name, name),
    FOREIGN KEY(chroot_name) REFERENCES chroots(name) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT 'ok',
    message TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fs_mutations (
    mutation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    destination_path TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fs_mutations_state ON fs_mutations(state, updated_at);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    target TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    expires_at REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at);
"""

class ChrootRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._write_lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
        self._migrate_snapshots_foreign_key()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _migrate_snapshots_foreign_key(self) -> None:
        with self._write_lock, self.connect() as conn:
            fk_rows = conn.execute("PRAGMA foreign_key_list(snapshots)").fetchall()
            if any(
                str(row[2]) == "chroots"
                and str(row[5]).upper() == "CASCADE"
                and str(row[6]).upper() == "CASCADE"
                for row in fk_rows
            ):
                return
            orphan_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM snapshots s LEFT JOIN chroots c ON c.name = s.chroot_name WHERE c.name IS NULL"
                ).fetchone()[0]
            )
            if orphan_count:
                raise RuntimeError(
                    f"registry contains {orphan_count} orphan snapshot row(s); refusing to discard them while adding foreign-key integrity"
                )
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    CREATE TABLE snapshots_new (
                        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        chroot_name TEXT NOT NULL,
                        path TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'copy',
                        note TEXT NOT NULL DEFAULT '',
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chroot_name, name),
                        FOREIGN KEY(chroot_name) REFERENCES chroots(name) ON UPDATE CASCADE ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO snapshots_new
                        (snapshot_id, name, chroot_name, path, kind, note, size_bytes, metadata_json, created_at)
                    SELECT s.snapshot_id, s.name, s.chroot_name, s.path, s.kind, s.note, s.size_bytes, s.metadata_json, s.created_at
                    FROM snapshots s JOIN chroots c ON c.name = s.chroot_name
                    """
                )
                conn.execute("DROP TABLE snapshots")
                conn.execute("ALTER TABLE snapshots_new RENAME TO snapshots")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")

    def upsert(
        self,
        *,
        name: str,
        distro: str,
        path: str,
        phase: str,
        installed: bool = False,
        arch: str | None = None,
        release_name: str | None = None,
        version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = json.dumps(metadata or {}, sort_keys=True)
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chroots (name, distro, path, arch, release_name, version, phase, installed, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    distro=excluded.distro,
                    path=excluded.path,
                    arch=excluded.arch,
                    release_name=excluded.release_name,
                    version=excluded.version,
                    phase=excluded.phase,
                    installed=excluded.installed,
                    metadata_json=excluded.metadata_json
                """,
                (name, distro, path, arch, release_name, version, phase, int(installed), payload),
            )

    def apply_chroot_mutations(self, mutations: list[dict[str, Any]]) -> None:
        """Apply a preflighted set of chroot registry mutations in one SQLite transaction."""
        with self._write_lock, self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for mutation in mutations:
                action = str(mutation.get("action") or "")
                name = str(mutation.get("name") or "")
                if not name:
                    raise ValueError("registry mutation requires name")
                if action == "delete":
                    conn.execute("DELETE FROM chroots WHERE name = ?", (name,))
                    continue
                if action != "upsert":
                    raise ValueError(f"unsupported registry mutation action: {action}")
                payload = json.dumps(mutation.get("metadata") or {}, sort_keys=True)
                conn.execute(
                    """
                    INSERT INTO chroots (name, distro, path, arch, release_name, version, phase, installed, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        distro=excluded.distro,
                        path=excluded.path,
                        arch=excluded.arch,
                        release_name=excluded.release_name,
                        version=excluded.version,
                        phase=excluded.phase,
                        installed=excluded.installed,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        name,
                        str(mutation.get("distro") or "unknown"),
                        str(mutation.get("path") or ""),
                        mutation.get("arch"),
                        mutation.get("release_name"),
                        mutation.get("version"),
                        str(mutation.get("phase") or "registered"),
                        int(bool(mutation.get("installed"))),
                        payload,
                    ),
                )

    def get(self, name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chroots WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return dict(row) | {"metadata": _safe_json_dict(row["metadata_json"], field="chroots.metadata_json")}

    def find_by_path(self, path: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chroots WHERE path = ? LIMIT 1", (path,)).fetchone()
        if row is None:
            return None
        return dict(row) | {"metadata": _safe_json_dict(row["metadata_json"], field="chroots.metadata_json")}

    def rename(self, old_name: str, new_name: str, *, new_path: str | None = None) -> None:
        record = self.get(old_name)
        if record is None:
            raise KeyError(old_name)
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "UPDATE chroots SET name = ?, path = ? WHERE name = ?",
                (new_name, new_path or record["path"], old_name),
            )

    def delete(self, name: str) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM chroots WHERE name = ?", (name,))

    def list(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name, distro, path, arch, release_name, version, phase, installed, metadata_json, created_at, updated_at FROM chroots ORDER BY name"
            ).fetchall()
        return [
            dict(row) | {"metadata": _safe_json_dict(row["metadata_json"], field="chroots.metadata_json")}
            for row in rows
        ]



    def add_snapshot(
        self,
        *,
        name: str,
        chroot_name: str,
        path: str,
        kind: str = "copy",
        note: str = "",
        size_bytes: int = 0,
        metadata: dict[str, Any] | None = None,
    ):
        payload = json.dumps(metadata or {}, sort_keys=True)
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots (name, chroot_name, path, kind, note, size_bytes, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chroot_name, name) DO UPDATE SET
                    path=excluded.path,
                    kind=excluded.kind,
                    note=excluded.note,
                    size_bytes=excluded.size_bytes,
                    metadata_json=excluded.metadata_json
                """,
                (name, chroot_name, path, kind, note, int(size_bytes), payload),
            )
            snapshot_id = int(cursor.lastrowid or 0)
        if snapshot_id:
            return self.get_snapshot(snapshot_id)
        return self.get_snapshot_by_name(chroot_name, name)

    def get_snapshot(self, snapshot_id: int):
        row = None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        from .models import SnapshotRecord
        metadata = _safe_json_dict(row["metadata_json"], field="snapshots.metadata_json")
        return SnapshotRecord(
            snapshot_id=int(row["snapshot_id"]),
            name=str(row["name"]),
            chroot_name=str(row["chroot_name"]),
            path=str(row["path"]),
            kind=str(row["kind"]),
            created_at=str(row["created_at"]),
            note=str(row["note"]),
            size_bytes=int(row["size_bytes"] or 0),
            metadata={str(key): str(value) for key, value in metadata.items()} if isinstance(metadata, dict) else {},
        )

    def get_snapshot_by_name(self, chroot_name: str, name: str):
        row = None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE chroot_name = ? AND name = ?", (chroot_name, name)).fetchone()
        if row is None:
            raise KeyError((chroot_name, name))
        return self.get_snapshot(int(row["snapshot_id"]))

    def list_snapshots(self, *, chroot_name: str | None = None, limit: int = 100):
        from .models import SnapshotRecord
        query = "SELECT * FROM snapshots"
        params: tuple[Any, ...]
        if chroot_name:
            query += " WHERE chroot_name = ?"
            params = (chroot_name, int(limit))
        else:
            params = (int(limit),)
        query += " ORDER BY snapshot_id DESC LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        items = []
        for row in rows:
            metadata = _safe_json_dict(row["metadata_json"], field="snapshots.metadata_json")
            items.append(
                SnapshotRecord(
                    snapshot_id=int(row["snapshot_id"]),
                    name=str(row["name"]),
                    chroot_name=str(row["chroot_name"]),
                    path=str(row["path"]),
                    kind=str(row["kind"]),
                    created_at=str(row["created_at"]),
                    note=str(row["note"]),
                    size_bytes=int(row["size_bytes"] or 0),
                    metadata={str(key): str(value) for key, value in metadata.items()} if isinstance(metadata, dict) else {},
                )
            )
        return items

    def delete_snapshot(self, snapshot_id: int) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))

    def begin_fs_mutation(
        self,
        *,
        kind: str,
        target: str = "",
        source_path: str = "",
        destination_path: str = "",
        detail: dict[str, Any] | None = None,
    ) -> str:
        mutation_id = uuid.uuid4().hex
        now = time.time()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO fs_mutations (mutation_id, kind, target, source_path, destination_path, state, detail_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (mutation_id, kind, target, source_path, destination_path, json.dumps(detail or {}, sort_keys=True), now, now),
            )
        return mutation_id

    def update_fs_mutation(self, mutation_id: str, state: str, *, detail: dict[str, Any] | None = None) -> None:
        with self._write_lock, self.connect() as conn:
            current = conn.execute("SELECT detail_json FROM fs_mutations WHERE mutation_id = ?", (mutation_id,)).fetchone()
            merged = _safe_json_dict(current["detail_json"], field="fs_mutations.detail_json") if current is not None else {}
            # Corruption diagnostics are useful for reads, but do not perpetuate
            # synthetic marker fields into newly-written mutation state.
            if merged.get("_corrupt"):
                merged = {}
            merged.update(detail or {})
            conn.execute(
                "UPDATE fs_mutations SET state = ?, detail_json = ?, updated_at = ? WHERE mutation_id = ?",
                (state, json.dumps(merged, sort_keys=True), time.time(), mutation_id),
            )

    def pending_fs_mutations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fs_mutations WHERE state IN ('pending', 'staged', 'promoting', 'committed') ORDER BY updated_at ASC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            dict(row) | {"detail": _safe_json_dict(row["detail_json"], field="fs_mutations.detail_json")}
            for row in rows
        ]

    def register_artifact(
        self,
        *,
        path: str,
        kind: str,
        target: str = "",
        size_bytes: int = 0,
        ttl_seconds: int | None = 7 * 24 * 60 * 60,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
        artifact_id = uuid.uuid4().hex
        with self._write_lock, self.connect() as conn:
            existing = conn.execute("SELECT artifact_id, created_at FROM artifacts WHERE path = ?", (path,)).fetchone()
            if existing is not None:
                artifact_id = str(existing["artifact_id"])
                created_at = float(existing["created_at"])
            else:
                created_at = now
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, kind, path, target, size_bytes, created_at, expires_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET kind=excluded.kind, target=excluded.target, size_bytes=excluded.size_bytes, expires_at=excluded.expires_at, metadata_json=excluded.metadata_json
                """,
                (artifact_id, kind, path, target, int(size_bytes), created_at, expires_at, json.dumps(metadata or {}, sort_keys=True)),
            )
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return dict(row) | {"metadata": _safe_json_dict(row["metadata_json"], field="artifacts.metadata_json")}

    def artifact_by_path(self, path: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE path = ?", (path,)).fetchone()
        return None if row is None else dict(row) | {"metadata": _safe_json_dict(row["metadata_json"], field="artifacts.metadata_json")}

    def list_artifacts(self, *, include_expired: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        now = time.time()
        query = "SELECT * FROM artifacts" if include_expired else "SELECT * FROM artifacts WHERE expires_at IS NULL OR expires_at > ?"
        params: tuple[Any, ...] = () if include_expired else (now,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params = (*params, int(limit))
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            dict(row) | {"metadata": _safe_json_dict(row["metadata_json"], field="artifacts.metadata_json")}
            for row in rows
        ]

    def delete_artifact(self, artifact_id: str) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))

    def prune_expired_artifacts(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._write_lock, self.connect() as conn:
            rows = conn.execute("SELECT * FROM artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)).fetchall()
            conn.execute("DELETE FROM artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        return [dict(row) for row in rows]

    def add_event(
        self,
        *,
        event_type: str,
        actor: str,
        target: str = "",
        result: str = "ok",
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ):
        payload = json.dumps(metadata or {}, sort_keys=True)
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (event_type, actor, target, result, message, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_type, actor, target, result, message, payload),
            )
            event_id = int(cursor.lastrowid)
        return self.get_event(event_id)

    def get_event(self, event_id: int):
        row = None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        from .models import AuditEvent

        metadata = _safe_json_dict(row["metadata_json"], field="events.metadata_json")
        return AuditEvent(
            event_id=int(row["event_id"]),
            event_type=str(row["event_type"]),
            actor=str(row["actor"]),
            target=str(row["target"]),
            result=str(row["result"]),
            message=str(row["message"]),
            created_at=str(row["created_at"]),
            metadata={str(key): str(value) for key, value in metadata.items()} if isinstance(metadata, dict) else {},
        )

    def list_events(self, *, limit: int = 20):
        from .models import AuditEvent

        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY event_id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        events = []
        for row in rows:
            metadata = _safe_json_dict(row["metadata_json"], field="events.metadata_json")
            events.append(
                AuditEvent(
                    event_id=int(row["event_id"]),
                    event_type=str(row["event_type"]),
                    actor=str(row["actor"]),
                    target=str(row["target"]),
                    result=str(row["result"]),
                    message=str(row["message"]),
                    created_at=str(row["created_at"]),
                    metadata={str(key): str(value) for key, value in metadata.items()} if isinstance(metadata, dict) else {},
                )
            )
        return events
