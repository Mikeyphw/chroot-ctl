from pathlib import Path

import pytest

import chrootctl.native_runtime_update as updates
from chrootctl.native_runtime_update import stage_native_runtime_update, validate_staged_native_runtime


def test_missing_runtime_update_is_rejected(tmp_path: Path) -> None:
    with pytest.raises((ValueError, FileNotFoundError, NotADirectoryError)):
        validate_staged_native_runtime(tmp_path / "missing")


def test_stage_native_runtime_update_rejects_symlink_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "link"
    link.symlink_to(source, target_is_directory=True)
    monkeypatch.setattr(updates, "validate_native_runtime_artifact", lambda path: {"ok": True})

    with pytest.raises(ValueError, match="real directory"):
        stage_native_runtime_update(link, tmp_path / "dest")


def test_stage_native_runtime_update_copies_through_validated_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def fake_validate(path: Path) -> dict[str, object]:
        calls.append(path)
        return {"ok": True}

    source = tmp_path / "source"
    source.mkdir()
    (source / "runtime-manifest.json").write_text("{}", encoding="utf-8")
    (source / "chrootctl.dist").mkdir()
    (source / "chrootctl.dist" / "chrootctl").write_text("bin", encoding="utf-8")

    monkeypatch.setattr(updates, "validate_native_runtime_artifact", fake_validate)
    destination = tmp_path / "missing-parent" / "runtime"

    plan = stage_native_runtime_update(source, destination)

    assert plan.source == source.resolve()
    assert plan.destination == destination.resolve()
    assert (destination / "runtime-manifest.json").read_text(encoding="utf-8") == "{}"
    assert len(calls) == 2
