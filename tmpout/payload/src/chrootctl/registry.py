from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

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
    UNIQUE(chroot_name, name)
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
"""

class ChrootRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
        with self.connect() as conn:
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

    def get(self, name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chroots WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return dict(row) | {"metadata": json.loads(row["metadata_json"])}

    def rename(self, old_name: str, new_name: str, *, new_path: str | None = None) -> None:
        record = self.get(old_name)
        if record is None:
            raise KeyError(old_name)
        with self.connect() as conn:
            conn.execute(
                "UPDATE chroots SET name = ?, path = ? WHERE name = ?",
                (new_name, new_path or record["path"], old_name),
            )

    def delete(self, name: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chroots WHERE name = ?", (name,))

    def list(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name, distro, path, release_name, version, phase, installed, created_at, updated_at FROM chroots ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]



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
        with self.connect() as conn:
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
        metadata = json.loads(str(row["metadata_json"] or "{}"))
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
            metadata = json.loads(str(row["metadata_json"] or "{}"))
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
        with self.connect() as conn:
            conn.execute("DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))

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
        with self.connect() as conn:
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

        metadata = json.loads(str(row["metadata_json"] or "{}"))
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
            metadata = json.loads(str(row["metadata_json"] or "{}"))
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
