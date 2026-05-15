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

    def list(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name, distro, path, release_name, version, phase, installed, created_at, updated_at FROM chroots ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]
