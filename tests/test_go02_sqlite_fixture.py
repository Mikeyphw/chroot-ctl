from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "go02-sqlite-fixture.py"


def _load_fixture_module():
    spec = importlib.util.spec_from_file_location("go02_sqlite_fixture", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_go02_python_fixture_uses_real_registry_and_legacy_pragmas(tmp_path: Path) -> None:
    fixture = _load_fixture_module()
    db = tmp_path / "registry.sqlite3"
    result = fixture.create_fixture(db)
    assert result["pragmas"] == {
        "journal_mode": "wal",
        "synchronous": 2,
        "busy_timeout": 5000,
        "foreign_keys": 1,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
    }
    registry = fixture.ChrootRegistry(db)
    assert registry.get("python-seed")["metadata"] == {"roundTrip": True, "writer": "python"}
    assert registry.get_snapshot_by_name("python-seed", "python-snapshot").chroot_name == "python-seed"


def test_go02_keeps_sqlite_spike_out_of_production_go_main() -> None:
    source = (ROOT / "cmd" / "chrootctl" / "main.go").read_text(encoding="utf-8")
    assert "internal/sqlitecompat" not in source
