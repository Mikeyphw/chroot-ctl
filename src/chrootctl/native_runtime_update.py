from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .native_runtime import validate_native_runtime_artifact


@dataclass(frozen=True, slots=True)
class NativeRuntimeUpdatePlan:
    source: Path
    destination: Path


def validate_staged_native_runtime(path: Path) -> dict[str, object]:
    return validate_native_runtime_artifact(path)


def stage_native_runtime_update(source: Path, destination: Path) -> NativeRuntimeUpdatePlan:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()

    if source.is_symlink() or not source.is_dir():
        raise ValueError("native runtime update source must be a real directory")

    validate_staged_native_runtime(source)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="native-runtime-update-", dir=str(destination.parent)) as tmp:
        staged = Path(tmp) / "runtime"
        shutil.copytree(source, staged, symlinks=False)
        validate_staged_native_runtime(staged)

        if destination.exists():
            if destination.is_symlink():
                raise ValueError("refusing symlink native runtime destination")
            if not destination.is_dir():
                raise ValueError("native runtime destination must be a directory")
            shutil.rmtree(destination)

        shutil.copytree(staged, destination, symlinks=False)

    return NativeRuntimeUpdatePlan(source=source, destination=destination)
