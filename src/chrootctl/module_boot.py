from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

_TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def load_startup_targets(state_path: Path) -> tuple[str, ...]:
    expanded = state_path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ValueError(f"module boot target state is missing or unsafe: {expanded}")
    state_path = expanded.resolve()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("module boot target state must be a JSON object")
    items = payload.get("startup_targets", [])
    if not isinstance(items, list):
        raise ValueError("startup_targets must be a list")
    names: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            raise ValueError(f"invalid startup target: {raw!r}")
        name = raw.strip()
        if not _TARGET_RE.fullmatch(name):
            raise ValueError(f"invalid startup target: {raw!r}")
        if name not in seen:
            seen.add(name)
            names.append(name)
    return tuple(names)


def run_module_boot(state_path: Path) -> None:
    from .bridge.dispatcher import operation_root_for
    from .operations import OperationManager
    from .services import create_service_container

    names = load_startup_targets(state_path)
    services = create_service_container()
    manager = OperationManager(operation_root_for(services))
    manager.recover()
    for name in names:
        request = {
            "protocolVersion": 1,
            "requestId": f"module-boot-{name}",
            "operation": "module.boot.start",
            "payload": {"name": name, "source": "preview-approved-module-state"},
        }
        record = manager.create(
            kind="module.boot.start",
            title=f"Module boot start {name}",
            target_name=name,
            request=request,
            retry=None,
            lock_scope="target",
        )
        completed = manager.execute(
            record,
            lambda progress, cancelled, target=name: services.chroots().start(
                target,
                login=False,
                root_login=False,
                interactive=False,
            ),
        )
        if completed.state != "succeeded":
            raise RuntimeError(f"module boot start failed for {name}: {completed.state}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chrootctl __module-boot", description=argparse.SUPPRESS)
    parser.add_argument("state_file", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    run_module_boot(args.state_file)
    return 0
