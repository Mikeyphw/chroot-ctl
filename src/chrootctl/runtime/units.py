from __future__ import annotations

import configparser
import fcntl
import json
import os
import shlex
import signal
import tempfile
import threading
import stat
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from ..config import ChrootConfig
from ..controller import ChrootController
from ..services.chroots import validate_chroot_name
from ..user_sync import validate_username
from ..system import ProcessIdentity, capture_process_identity, process_identity_matches, signal_process_identity
from .common import console, emit_panel, emit_table

if TYPE_CHECKING:
    from .core import RuntimeContext


@dataclass(frozen=True, slots=True)
class ServiceUnit:
    name: str
    path: Path
    description: str = ""
    chroot: str = ""
    user: str | None = None
    exec_start: str = ""
    exec_stop: str | None = None
    working_directory: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    x11: bool = False
    root: bool = False
    restart: str = "no"
    install_enabled: bool = False
    wanted_by: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.install_enabled

    def runs_as_root(self) -> bool:
        return self.root or (self.user or "").lower() == "root"

    def command_text(self) -> str:
        parts: list[str] = []
        for key, value in self.environment.items():
            parts.append(f"export {key}={shlex.quote(value)}")
        if self.working_directory:
            parts.append(f"cd {shlex.quote(self.working_directory)}")
        parts.append(f"exec {self.exec_start}")
        return "; ".join(parts)


class ServiceCatalog:
    def __init__(self, config: ChrootConfig) -> None:
        self.config = config

    def list_units(self) -> list[ServiceUnit]:
        units: dict[str, ServiceUnit] = {}
        for directory in self.config.service_dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.iterdir()):
                if path.suffix != ".service" or not path.is_file():
                    continue
                unit = load_service_unit(path)
                units[unit.name] = unit
        return [units[name] for name in sorted(units)]

    def get(self, name: str) -> ServiceUnit:
        normalized = _normalize_unit_name(name)
        for unit in self.list_units():
            if unit.name == normalized:
                return unit
        searched = ", ".join(str(path) for path in self.config.service_dirs)
        raise RuntimeError(f"unknown service unit: {normalized}; searched {searched or 'no service_dirs configured'}")

    def by_name(self) -> dict[str, ServiceUnit]:
        return {unit.name: unit for unit in self.list_units()}


class ServiceRunner:
    def __init__(self, context: RuntimeContext | Any) -> None:
        self.context = context
        self.catalog = ServiceCatalog(context.config)

    @classmethod
    def from_services(cls, services: Any) -> "ServiceRunner":
        runtime = services.runtime_for()
        return cls(SimpleNamespace(config=services.base_config, runner=runtime.runner, logger=services.logger))

    def list(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for unit in self.catalog.list_units():
            rows.append(
                {
                    "service": unit.name,
                    "chroot": unit.chroot,
                    "enabled": "yes" if self.is_enabled(unit) else "no",
                    "boot": "yes" if self.is_enabled(unit) and "boot.target" in unit.wanted_by else "no",
                    "wanted_by": ",".join(unit.wanted_by),
                    "after": ",".join(unit.after),
                    "requires": ",".join(unit.requires),
                    "status": self.status(unit.name)["status"],
                    "description": unit.description,
                }
            )
        return rows


    def start(self, unit_name: str, *, chroot: str | None = None, foreground: bool = False) -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        with _service_lock(self.context.config.service_state_dir, chroot_name, dry_run=self.context.runner.dry_run):
            return self._start_unit(unit, chroot=chroot_name, foreground=foreground)

    def restart(self, unit_name: str, *, chroot: str | None = None) -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        with _service_lock(self.context.config.service_state_dir, chroot_name, dry_run=self.context.runner.dry_run):
            stop_result = self._stop_unit(unit, chroot_name)
            start_result = self._start_unit(unit, chroot=chroot_name, foreground=False)
            return {"stopped": stop_result, "started": start_result}

    def stop(self, unit_name: str, *, chroot: str | None = None) -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        with _service_lock(self.context.config.service_state_dir, chroot_name, dry_run=self.context.runner.dry_run):
            return self._stop_unit(unit, chroot_name)

    def _stop_unit(self, unit: ServiceUnit, chroot_name: str) -> dict[str, Any]:
        pid_file = self._pid_file(chroot_name, unit.name)
        identity_file = self._identity_file(chroot_name, unit.name)
        log_file = self._log_file(chroot_name, unit.name)
        pid = _read_pid(pid_file)
        identity = _read_process_identity(identity_file)
        if pid is None:
            _append_journal(log_file, "stop requested; no pid file")
            return {"service": unit.name, "chroot": chroot_name, "status": "stopped", "detail": "no pid file", "log_file": str(log_file)}
        if identity is None or identity.pid != pid or not process_identity_matches(identity):
            _unlink(pid_file); _unlink(identity_file)
            _append_journal(log_file, f"refused stop hooks/signals for stale or unverified pid {pid}")
            return {"service": unit.name, "chroot": chroot_name, "status": "stopped", "detail": f"stale/unverified pid {pid}", "log_file": str(log_file)}

        if unit.exec_stop:
            cfg = self.context.config.for_chroot(chroot_name)
            controller = ChrootController(cfg, self.context.runner, self.context.logger)
            _append_journal(log_file, f"ExecStop: {unit.exec_stop}")
            controller.exec(root=unit.runs_as_root(), command=unit.exec_stop, x11=unit.x11, username=unit.user)
        if not process_identity_matches(identity):
            _unlink(pid_file); _unlink(identity_file)
            return {"service": unit.name, "chroot": chroot_name, "status": "stopped", "pid": pid, "log_file": str(log_file)}
        signal_process_identity(identity, signal.SIGTERM)
        for _ in range(20):
            if not process_identity_matches(identity):
                _unlink(pid_file); _unlink(identity_file)
                _append_journal(log_file, f"stopped pid {pid}")
                return {"service": unit.name, "chroot": chroot_name, "status": "stopped", "pid": pid, "log_file": str(log_file)}
            time.sleep(0.1)
        signal_process_identity(identity, signal.SIGKILL)
        for _ in range(20):
            if not process_identity_matches(identity):
                _unlink(pid_file); _unlink(identity_file)
                _append_journal(log_file, f"killed verified pid {pid}")
                return {"service": unit.name, "chroot": chroot_name, "status": "killed", "pid": pid, "log_file": str(log_file)}
            time.sleep(0.1)
        _append_journal(log_file, f"SIGKILL sent to verified pid {pid}, but process identity still exists; retaining control state")
        return {
            "service": unit.name, "chroot": chroot_name, "status": "kill-pending", "pid": pid,
            "detail": "verified process still exists after SIGKILL; control state retained", "log_file": str(log_file),
        }

    def status(self, unit_name: str, *, chroot: str | None = None) -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        pid_file = self._pid_file(chroot_name, unit.name)
        identity_file = self._identity_file(chroot_name, unit.name)
        pid = _read_pid(pid_file)
        identity = _read_process_identity(identity_file)
        base = {"service": unit.name, "chroot": chroot_name, "enabled": self.is_enabled(unit), "wanted_by": unit.wanted_by, "after": unit.after, "requires": unit.requires, "restart": unit.restart, "pid_file": str(pid_file), "log_file": str(self._log_file(chroot_name, unit.name))}
        if pid is None:
            return {**base, "status": "stopped"}
        if identity is not None and identity.pid == pid and process_identity_matches(identity):
            return {**base, "status": "running", "pid": pid}
        return {**base, "status": "stale", "pid": pid, "detail": "PID identity missing or no longer matches"}

    def logs(self, unit_name: str, *, chroot: str | None = None, tail: int | None = None) -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        log_file = self._log_file(chroot_name, unit.name)
        if not log_file.exists():
            return {"service": unit.name, "chroot": chroot_name, "log_file": str(log_file), "text": ""}
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if tail is not None:
            lines = lines[-tail:]
        return {"service": unit.name, "chroot": chroot_name, "log_file": str(log_file), "text": "\n".join(lines)}

    def enable(self, unit_name: str, *, chroot: str | None = None, target: str = "boot.target") -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        if target not in unit.wanted_by:
            raise RuntimeError(f"service {unit.name} is not installable for {target}; WantedBy={','.join(unit.wanted_by) or '(none)'}")
        marker = self._enabled_marker(chroot_name, unit.name, target)
        disabled = self._disabled_marker(chroot_name, unit.name)
        if not self.context.runner.dry_run:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(unit.path) + "\n", encoding="utf-8")
            _unlink(disabled)
        return {"service": unit.name, "chroot": chroot_name, "target": target, "enabled": True, "marker": str(marker)}

    def disable(self, unit_name: str, *, chroot: str | None = None, target: str = "boot.target") -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        for wanted in unit.wanted_by or (target,):
            _unlink(self._enabled_marker(chroot_name, unit.name, wanted))
        disabled = self._disabled_marker(chroot_name, unit.name)
        if not self.context.runner.dry_run:
            disabled.parent.mkdir(parents=True, exist_ok=True)
            disabled.write_text(str(unit.path) + "\n", encoding="utf-8")
        return {"service": unit.name, "chroot": chroot_name, "target": target, "enabled": False, "marker": str(disabled)}

    def is_enabled(self, unit: ServiceUnit, *, target: str = "boot.target") -> bool:
        if self._disabled_marker(unit.chroot, unit.name).exists():
            return False
        if self._enabled_marker(unit.chroot, unit.name, target).exists():
            return True
        return unit.install_enabled and target in unit.wanted_by

    def boot(self, *, target: str = "boot.target", parallel: bool = True) -> list[dict[str, Any]]:
        graph = self._boot_graph(target)
        layers = _dependency_layers(graph)
        results: list[dict[str, Any]] = []
        for layer_index, layer in enumerate(layers, start=1):
            if parallel and len(layer) > 1:
                with ThreadPoolExecutor(max_workers=len(layer)) as executor:
                    future_map = {
                        executor.submit(self.start, graph[name].name, chroot=graph[name].chroot, foreground=False): name
                        for name in layer
                    }
                    for future in as_completed(future_map):
                        name = future_map[future]
                        try:
                            row = future.result()
                        except Exception as exc:  # keep boot progressing and expose exact failed unit
                            row = {"service": name, "chroot": graph[name].chroot, "status": "failed", "error": str(exc)}
                        row["target"] = target
                        row["layer"] = layer_index
                        results.append(row)
            else:
                for name in layer:
                    unit = graph[name]
                    try:
                        row = self.start(unit.name, chroot=unit.chroot, foreground=False)
                    except Exception as exc:
                        row = {"service": name, "chroot": unit.chroot, "status": "failed", "error": str(exc)}
                    row["target"] = target
                    row["layer"] = layer_index
                    results.append(row)
        return sorted(results, key=lambda row: (int(row.get("layer", 0)), str(row.get("service", ""))))

    def _boot_graph(self, target: str) -> dict[str, ServiceUnit]:
        all_units = self.catalog.by_name()
        selected: dict[str, ServiceUnit] = {}

        def add_with_requires(unit: ServiceUnit) -> None:
            if unit.name in selected:
                return
            selected[unit.name] = unit
            for required in unit.requires:
                required_name = _normalize_unit_name(required)
                if required_name not in all_units:
                    raise RuntimeError(f"service {unit.name} requires missing unit {required_name}")
                add_with_requires(all_units[required_name])

        for unit in all_units.values():
            if target in unit.wanted_by and self.is_enabled(unit, target=target):
                add_with_requires(unit)
        return selected


    def _start_unit(self, unit: ServiceUnit, *, chroot: str, foreground: bool) -> dict[str, Any]:
        if not unit.exec_start.strip():
            raise RuntimeError(f"service {unit.name} is missing Service.ExecStart")
        if not foreground:
            current = self.status(unit.name, chroot=chroot)
            if current["status"] == "running":
                return {"service": unit.name, "chroot": chroot, "status": "already-running", "pid": current.get("pid"), "log_file": current.get("log_file")}
        cfg = self.context.config.for_chroot(chroot)
        controller = ChrootController(cfg, self.context.runner, self.context.logger)
        mount_result = controller.mount()
        if getattr(mount_result, "failed", 0):
            raise RuntimeError(f"cannot start {unit.name}: chroot mount failed: {'; '.join(getattr(mount_result, 'errors', []))}")
        tty_result = controller.fix_tty()
        if getattr(tty_result, "failed", 0):
            raise RuntimeError(f"cannot start {unit.name}: tty/device preparation failed: {'; '.join(getattr(tty_result, 'errors', []))}")
        if unit.x11:
            controller._prepare_x11_host()
        log_file = self._log_file(chroot, unit.name)
        service_user = "root" if unit.runs_as_root() else (unit.user or cfg.username)
        script_path = self._write_service_script(cfg, chroot, unit, service_user=service_user)
        _append_journal(log_file, f"starting {unit.name}.service in chroot={chroot} user={service_user}")
        _append_journal(log_file, f"ExecStart: {unit.exec_start}")
        _append_journal(log_file, f"ServiceScript: {script_path}")
        argv, env = controller.service_invocation(root=unit.runs_as_root(), command=str(script_path), x11=unit.x11, username=unit.user)
        if foreground:
            result = self.context.runner.run(argv, check=False, env=env, chroot_env=True, capture_output=False)
            code = result.returncode
            _append_journal(log_file, f"foreground process exited returncode={code}")
            return {"service": unit.name, "chroot": chroot, "status": "exited", "returncode": code, "log_file": str(log_file)}
        pid = self.context.runner.spawn(argv, env=env, chroot_env=True, stdout_path=log_file)
        if self.context.runner.dry_run:
            return {"service": unit.name, "chroot": chroot, "status": "started", "pid": pid, "log_file": str(log_file)}
        identity = capture_process_identity(pid)
        if identity is None or identity.start_time_ticks is None or not identity.boot_id:
            try: os.kill(pid, signal.SIGTERM)
            except ProcessLookupError: pass
            raise RuntimeError(f"cannot persist strong process identity for service {unit.name}")
        pid_file = self._pid_file(chroot, unit.name)
        identity_file = self._identity_file(chroot, unit.name)
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        _atomic_text(pid_file, f"{pid}\n", mode=0o600)
        _atomic_text(identity_file, json.dumps(identity.to_dict(), sort_keys=True) + "\n", mode=0o600)
        _append_journal(log_file, f"spawned verified pid={pid}")
        return {"service": unit.name, "chroot": chroot, "status": "started", "pid": pid, "pid_file": str(pid_file), "log_file": str(log_file)}

    def _write_service_script(self, cfg: ChrootConfig, chroot: str, unit: ServiceUnit, *, service_user: str) -> str:
        script_root = cfg.chroot_base / "run" / "chrootctl" / "services"
        token = f"{_safe_name(chroot)}-{_safe_name(unit.name)}-{uuid.uuid4().hex}"
        if self.context.runner.dry_run:
            return f"/run/chrootctl/services/{token}/run.sh"
        # The shared directory is root-owned and searchable but not listable. Each
        # randomized invocation directory is then restricted to root + the exact
        # chroot user's primary group, keeping generated scripts root-owned while
        # still executable by a non-root service account.
        _prepare_service_root(script_root)
        service_gid = 0 if service_user == "root" else _chroot_user_gid(cfg, service_user)
        invocation_dir = script_root / token
        invocation_dir.mkdir(mode=0o700)
        if invocation_dir.is_symlink():
            raise RuntimeError(f"refusing symlink service invocation directory: {invocation_dir}")
        os.chown(invocation_dir, 0, service_gid)
        invocation_dir.chmod(0o700 if service_user == "root" else 0o710)
        script_path = invocation_dir / "run.sh"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(script_path, flags, 0o500 if service_user == "root" else 0o550)
        try:
            os.fchown(fd, 0, service_gid)
            os.fchmod(fd, 0o500 if service_user == "root" else 0o550)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_service_script_text(unit, service_user=service_user))
                handle.flush(); os.fsync(handle.fileno())
        except Exception:
            script_path.unlink(missing_ok=True)
            try: invocation_dir.rmdir()
            except OSError: pass
            raise
        return f"/run/chrootctl/services/{token}/run.sh"

    def _bound_chroot(self, unit: ServiceUnit, *, requested: str | None) -> str:
        bound = validate_chroot_name(unit.chroot, field=f"service {unit.name} Chroot")
        if requested is not None:
            requested = validate_chroot_name(requested, field="requested chroot")
        if requested and requested != bound:
            raise RuntimeError(f"service {unit.name} is bound to chroot {bound}; requested {requested}")
        return bound

    def _pid_file(self, chroot: str, unit_name: str) -> Path:
        return self.context.config.service_state_dir / f"{_safe_name(chroot)}-{_safe_name(unit_name)}.pid"

    def _identity_file(self, chroot: str, unit_name: str) -> Path:
        return self.context.config.service_state_dir / f"{_safe_name(chroot)}-{_safe_name(unit_name)}.identity.json"

    def _log_file(self, chroot: str, unit_name: str) -> Path:
        return self.context.config.service_log_dir / f"{_safe_name(chroot)}-{_safe_name(unit_name)}.journal"

    def _enabled_marker(self, chroot: str, unit_name: str, target: str) -> Path:
        return self.context.config.service_state_dir / "targets" / f"{_safe_name(target)}.wants" / f"{_safe_name(chroot)}-{_safe_name(unit_name)}.enabled"

    def _disabled_marker(self, chroot: str, unit_name: str) -> Path:
        return self.context.config.service_state_dir / "disabled" / f"{_safe_name(chroot)}-{_safe_name(unit_name)}.disabled"


def handle_run(context: RuntimeContext) -> None:
    runner = ServiceRunner(context)
    args = context.args
    chroot_name, unit_name = _resolve_run_targets(args)
    if args.run_list:
        emit_table(context, "Chroot Services", runner.list())
        return
    if args.boot:
        emit_table(context, "Boot Services", [_result_row(row) for row in runner.boot(target=args.target, parallel=not args.no_parallel)])
        return
    if unit_name is None:
        raise RuntimeError("run requires SERVICE, or CHROOT SERVICE")
    if args.run_status:
        emit_panel(context, "Service Status", runner.status(unit_name, chroot=chroot_name))
        return
    if args.logs:
        result = runner.logs(unit_name, chroot=chroot_name, tail=args.tail)
        console.print(result.get("text") or f"no journal: {result['log_file']}")
        if args.follow:
            _follow_file(Path(str(result["log_file"])))
        return
    if args.stop:
        emit_panel(context, "Service Stop", runner.stop(unit_name, chroot=chroot_name))
        return
    if args.restart:
        emit_panel(context, "Service Restart", runner.restart(unit_name, chroot=chroot_name))
        return
    emit_panel(context, "Service Start", runner.start(unit_name, chroot=chroot_name, foreground=args.foreground))


def handle_enable(context: RuntimeContext) -> None:
    runner = ServiceRunner(context)
    chroot_name, unit_name = _resolve_service_state_targets(context.args)
    emit_panel(context, "Service Enable", runner.enable(unit_name, chroot=chroot_name, target=context.args.target))


def handle_disable(context: RuntimeContext) -> None:
    runner = ServiceRunner(context)
    chroot_name, unit_name = _resolve_service_state_targets(context.args)
    emit_panel(context, "Service Disable", runner.disable(unit_name, chroot=chroot_name, target=context.args.target))


def handle_journal(context: RuntimeContext) -> None:
    runner = ServiceRunner(context)
    chroot_name, unit_name = _resolve_service_state_targets(context.args)
    result = runner.logs(unit_name, chroot=chroot_name, tail=context.args.tail)
    console.print(result.get("text") or f"no journal: {result['log_file']}")
    if context.args.follow:
        _follow_file(Path(str(result["log_file"])))


def load_service_unit(path: Path) -> ServiceUnit:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with path.open("r", encoding="utf-8") as handle:
        parser.read_file(handle)
    service = _section(parser, "Service")
    unit = _section(parser, "Unit")
    install = _section(parser, "Install")
    name = _normalize_unit_name(path.stem)
    exec_start = _get(service, "ExecStart", "")
    if not exec_start:
        raise RuntimeError(f"{path}: [Service] ExecStart is required")
    chroot = _get(service, "Chroot", "")
    if not chroot:
        raise RuntimeError(f"{path}: [Service] Chroot is required; services are bound to one chroot")
    user = _get(service, "User", None)
    _validate_unit_policy(path, parser)
    chroot = validate_chroot_name(chroot, field=f"{path} Service.Chroot")
    if user:
        user = validate_username(user)
    restart = (_get(service, "Restart", "no") or "no").lower()
    if restart not in {"no", "on-failure", "always"}:
        raise RuntimeError(f"{path}: unsupported Restart={restart}; expected no, on-failure, or always")
    return ServiceUnit(
        name=name,
        path=path,
        description=_get(unit, "Description", ""),
        chroot=chroot,
        user=user,
        root=_get_bool(service, "Root", False),
        exec_start=exec_start,
        exec_stop=_get(service, "ExecStop", None),
        working_directory=_get(service, "WorkingDirectory", None),
        environment=_parse_environment(_joined_repeated_values(path, "Service", "Environment", fallback=_get(service, "Environment", ""))),
        x11=_get_bool(service, "X11", False),
        restart=restart,
        install_enabled=_get_bool(install, "Enabled", False),
        wanted_by=_parse_words(_get(install, "WantedBy", "")),
        after=tuple(_normalize_unit_name(item) for item in _parse_words(_get(unit, "After", ""))),
        requires=tuple(_normalize_unit_name(item) for item in _parse_words(_get(unit, "Requires", ""))),
    )



def _service_script_text(unit: ServiceUnit, *, service_user: str) -> str:
    lines = [
        "#!/bin/sh",
        "# Generated by chrootctl. Do not edit; edit the .service unit instead.",
        "set -eu",
        "echo '[chrootctl-service] ===== preflight ====='",
        f"echo '[chrootctl-service] unit={shlex.quote(unit.name)} chroot={shlex.quote(unit.chroot)} requested_user={shlex.quote(service_user)}'",
        "echo \"[chrootctl-service] id=$(id 2>&1 || true)\"",
        "echo \"[chrootctl-service] shell=${SHELL:-} home=${HOME:-} user=${USER:-} pwd=$(pwd 2>/dev/null || true)\"",
    ]
    if unit.user and unit.user != "root":
        quoted_user = shlex.quote(unit.user)
        lines.extend(
            [
                f"if command -v getent >/dev/null 2>&1; then echo \"[chrootctl-service] passwd=$(getent passwd {quoted_user} 2>&1 || true)\"; fi",
                f"if command -v groups >/dev/null 2>&1; then echo \"[chrootctl-service] groups=$(groups {quoted_user} 2>&1 || true)\"; fi",
            ]
        )
    home_path = unit.environment.get("HOME") or ("/root" if unit.runs_as_root() else f"/home/{service_user}")
    lines.extend(
        [
            f"echo '[chrootctl-service] home stat:'",
            f"ls -ld {shlex.quote(home_path)} 2>&1 || true",
            f"echo '[chrootctl-service] first home entries:'",
            f"ls -la {shlex.quote(home_path)} 2>&1 | sed -n '1,80p' || true",
        ]
    )
    for key, value in unit.environment.items():
        lines.append(f"export {key}={shlex.quote(value)}")
    if unit.working_directory:
        quoted_workdir = shlex.quote(unit.working_directory)
        lines.extend(
            [
                f"echo '[chrootctl-service] workdir stat:'",
                f"ls -ld {quoted_workdir} 2>&1 || true",
                f"cd {quoted_workdir}",
            ]
        )
    lines.extend([
        "echo \"[chrootctl-service] exec cwd=$(pwd 2>/dev/null || true) home=${HOME:-}\"",
        "echo '[chrootctl-service] ===== exec ====='",
    ])
    if unit.restart == "no":
        lines.append(f"exec {unit.exec_start}")
    else:
        lines.extend([
            "while :; do",
            "  set +e",
            f"  {unit.exec_start}",
            "  rc=$?",
            "  set -e",
            f"  [ {shlex.quote(unit.restart)} = always ] || [ \"$rc\" -ne 0 ] || exit 0",
            "  echo \"[chrootctl-service] restart policy retry after rc=$rc\"",
            "  sleep 1",
            "done",
        ])
    lines.append("")
    return "\n".join(lines)



_SERVICE_LOCK_GUARD = threading.Lock()
_SERVICE_LOCKS: dict[str, threading.RLock] = {}

@contextmanager
def _service_lock(state_dir: Path, chroot: str, *, dry_run: bool = False):
    key = _safe_name(chroot)
    with _SERVICE_LOCK_GUARD:
        local_lock = _SERVICE_LOCKS.setdefault(key, threading.RLock())
    with local_lock:
        if dry_run:
            yield
            return
        lock_dir = state_dir / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if lock_dir.is_symlink() or not lock_dir.is_dir():
            raise RuntimeError(f"unsafe service lock directory: {lock_dir}")
        lock_dir.chmod(0o700)
        lock_path = lock_dir / f"{key}.lock"
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError(f"unsafe service lock file: {lock_path}")
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

def _prepare_service_root(path: Path) -> None:
    current = path
    parents = []
    while current != current.parent and not current.exists():
        parents.append(current); current = current.parent
    if current.is_symlink():
        raise RuntimeError(f"refusing symlink in service script path: {current}")
    for item in reversed(parents):
        item.mkdir(mode=0o700)
    control_root = path.parent
    for candidate in (control_root, path):
        if candidate.is_symlink() or not candidate.is_dir():
            raise RuntimeError(f"invalid service script directory: {candidate}")
        if candidate.stat().st_uid not in {0, os.geteuid()}:
            raise RuntimeError(f"service script directory has untrusted owner: {candidate}")
        try:
            os.chown(candidate, 0, 0)
        except PermissionError:
            if os.geteuid() == 0:
                raise
        # Searchable by the target service account, but directory contents are
        # not listable. The randomized invocation directory applies the exact
        # target group's tighter 0710 boundary.
        candidate.chmod(0o711)

def _chroot_user_gid(cfg: ChrootConfig, username: str) -> int:
    passwd = cfg.chroot_base / "etc" / "passwd"
    if passwd.is_symlink():
        raise RuntimeError(f"refusing symlink passwd file: {passwd}")
    try:
        lines = passwd.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as exc:
        raise RuntimeError(f"cannot resolve service user {username}: {exc}") from exc
    for line in lines:
        if not line or line.startswith("#"):
            continue
        fields = line.split(":")
        if len(fields) >= 4 and fields[0] == username:
            try:
                gid = int(fields[3])
            except ValueError as exc:
                raise RuntimeError(f"invalid primary gid for service user {username}") from exc
            if gid < 0:
                raise RuntimeError(f"invalid primary gid for service user {username}")
            return gid
    raise RuntimeError(f"service user does not exist in chroot passwd: {username}")

def _atomic_text(path: Path, text: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink state path: {path}")
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def _read_process_identity(path: Path) -> ProcessIdentity | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return ProcessIdentity.from_dict(raw) if isinstance(raw, dict) else None

def _validate_unit_policy(path: Path, parser: configparser.ConfigParser) -> None:
    allowed = {
        "Unit": {"Description", "After", "Requires"},
        "Service": {"Chroot", "User", "Root", "ExecStart", "ExecStop", "WorkingDirectory", "Environment", "X11", "Restart"},
        "Install": {"Enabled", "WantedBy"},
    }
    for section in parser.sections():
        if section not in allowed:
            raise RuntimeError(f"{path}: unsupported section [{section}]")
        for key in parser[section]:
            if key not in allowed[section]:
                raise RuntimeError(f"{path}: unsupported {section}.{key}")


def _dependency_layers(graph: dict[str, ServiceUnit]) -> list[list[str]]:
    pending = set(graph)
    layers: list[list[str]] = []
    while pending:
        ready: list[str] = []
        for name in sorted(pending):
            unit = graph[name]
            deps = {dep for dep in (*unit.requires, *unit.after) if dep in graph}
            if not deps.intersection(pending):
                ready.append(name)
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise RuntimeError(f"service dependency cycle or unsatisfied ordering among: {cycle}")
        layers.append(ready)
        pending.difference_update(ready)
    return layers



def _joined_repeated_values(path: Path, section: str, key: str, *, fallback: str | None = None) -> str:
    values = _read_repeated_values(path, section, key)
    if values:
        return " ".join(values)
    return fallback or ""


def _read_repeated_values(path: Path, section: str, key: str) -> list[str]:
    values: list[str] = []
    current_section: str | None = None
    last_was_target = False
    wanted_section = section.lower()
    wanted_key = key.lower()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            last_was_target = False
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip().lower()
            last_was_target = False
            continue
        if current_section != wanted_section:
            last_was_target = False
            continue
        if raw_line[0].isspace() and last_was_target and values:
            values[-1] = f"{values[-1]} {stripped}".strip()
            continue
        if "=" not in raw_line:
            last_was_target = False
            continue
        option, value = raw_line.split("=", 1)
        last_was_target = option.strip().lower() == wanted_key
        if last_was_target:
            values.append(value.strip())
    return values

def _section(parser: configparser.ConfigParser, name: str) -> configparser.SectionProxy | dict[str, str]:
    return parser[name] if parser.has_section(name) else {}


def _get(section: configparser.SectionProxy | dict[str, str], key: str, default: str | None) -> str | None:
    if key in section:
        value = str(section[key]).strip()
        return value if value else default
    lower = key.lower()
    for candidate, value in section.items():
        if str(candidate).lower() == lower:
            text = str(value).strip()
            return text if text else default
    return default


def _get_bool(section: configparser.SectionProxy | dict[str, str], key: str, default: bool) -> bool:
    value = _get(section, key, None)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"invalid boolean value for {key}: {value!r}")


def _parse_environment(raw: str | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if not raw:
        return env
    for token in shlex.split(raw):
        if "=" not in token:
            raise RuntimeError(f"invalid Environment token: {token}; expected KEY=value")
        key, value = token.split("=", 1)
        if not key.isidentifier():
            raise RuntimeError(f"invalid Environment name: {key}")
        env[key] = value
    return env


def _parse_words(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(word for word in shlex.split(raw.replace(",", " ")) if word)


def _resolve_run_targets(args: Any) -> tuple[str | None, str | None]:
    targets = list(getattr(args, "run_targets", []) or [])
    if len(targets) > 2:
        raise RuntimeError("run accepts SERVICE or CHROOT SERVICE")
    if len(targets) == 2:
        return targets[0], targets[1]
    if len(targets) == 1:
        return getattr(args, "name", None), targets[0]
    return getattr(args, "name", None), None


def _resolve_service_state_targets(args: Any) -> tuple[str | None, str]:
    targets = list(getattr(args, "service_targets", []) or [])
    if len(targets) > 2 or not targets:
        raise RuntimeError(f"{args.command} requires SERVICE, or CHROOT SERVICE")
    if len(targets) == 2:
        return targets[0], targets[1]
    return getattr(args, "name", None), targets[0]


def _result_row(row: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in row.items()}


def _normalize_unit_name(name: str) -> str:
    return name[:-8] if name.endswith(".service") else name


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _append_journal(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} chrootctl-service: {message}\n")


def _follow_file(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            while True:
                line = handle.readline()
                if line:
                    console.print(line.rstrip("\n"))
                    continue
                time.sleep(0.5)
    except FileNotFoundError:
        console.print(f"no journal: {path}")
    except KeyboardInterrupt:
        return
