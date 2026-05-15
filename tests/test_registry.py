from pathlib import Path
from chrootctl.registry import ChrootRegistry

def test_registry_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    reg = ChrootRegistry(db)
    reg.upsert(name="ubuntu", distro="ubuntu", path="/data/local/chroot/ubuntu", phase="extract")
    row = reg.get("ubuntu")
    assert row is not None
    assert row["name"] == "ubuntu"
