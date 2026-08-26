from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrootctl.module_boot import load_startup_targets


def test_module_boot_state_is_validated_and_deduplicated(tmp_path: Path) -> None:
    state = tmp_path / "boot_targets.json"
    state.write_text(json.dumps({"startup_targets": ["work", "dev", "work"]}), encoding="utf-8")
    assert load_startup_targets(state) == ("work", "dev")


@pytest.mark.parametrize("value", [["../bad"], ["bad/name"], [""], [123], "work"])
def test_module_boot_rejects_unsafe_target_state(tmp_path: Path, value: object) -> None:
    state = tmp_path / "boot_targets.json"
    state.write_text(json.dumps({"startup_targets": value}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_startup_targets(state)


def test_module_boot_rejects_symlink_state(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text('{"startup_targets":[]}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="missing or unsafe"):
        load_startup_targets(link)
