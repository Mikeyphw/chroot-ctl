from pathlib import Path
from chrootctl.registry import ChrootRegistry

def test_registry_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    reg = ChrootRegistry(db)
    reg.upsert(name="ubuntu", distro="ubuntu", path="/data/local/chroot/ubuntu", phase="extract")
    row = reg.get("ubuntu")
    assert row is not None
    assert row["name"] == "ubuntu"


def test_registry_rename_and_delete(tmp_path: Path) -> None:
    reg = ChrootRegistry(tmp_path / "db.sqlite3")
    reg.upsert(name="old", distro="ubuntu", path="/data/local/chroot/old", phase="extract")

    reg.rename("old", "new", new_path="/data/local/chroot/new")
    row = reg.get("new")

    assert row is not None
    assert row["path"] == "/data/local/chroot/new"

    reg.delete("new")
    assert reg.get("new") is None
