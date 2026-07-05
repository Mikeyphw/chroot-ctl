from __future__ import annotations

import configparser
import os
import shlex
import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from ..config import ChrootConfig
from ..controller import ChrootController
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
        return self._start_unit(unit, chroot=chroot_name, foreground=foreground)

    def restart(self, unit_name: str, *, chroot: str | None = None) -> dict[str, Any]:
        stop_result = self.stop(unit_name, chroot=chroot)
        start_result = self.start(unit_name, chroot=chroot)
        return {"stopped": stop_result, "started": start_result}

    def stop(self, unit_name: str, *, chroot: str | None = None) -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        pid_file = self._pid_file(chroot_name, unit.name)
        log_file = self._log_file(chroot_name, unit.name)
        pid = _read_pid(pid_file)
        stop_command = unit.exec_stop
        if stop_command:
            cfg = self.context.config.for_chroot(chroot_name)
            controller = ChrootController(cfg, self.context.runner, self.context.logger)
            _append_journal(log_file, f"ExecStop: {stop_command}")
            controller.exec(root=unit.runs_as_root(), command=stop_command, x11=unit.x11, username=unit.user)
        if pid is None:
            _append_journal(log_file, "stop requested; no pid file")
            return {"service": unit.name, "chroot": chroot_name, "status": "stopped", "detail": "no pid file", "log_file": str(log_file)}
        if not _pid_running(pid):
            _unlink(pid_file)
            _append_journal(log_file, f"removed stale pid {pid}")
            return {"service": unit.name, "chroot": chroot_name, "status": "stopped", "detail": f"stale pid {pid}", "log_file": str(log_file)}
        try:
            _append_journal(log_file, f"sending SIGTERM to process group {pid}")
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise PermissionError(f"cannot stop service {unit.name} pid {pid}: {exc}") from exc
        for _ in range(20):
            if not _pid_running(pid):
                _unlink(pid_file)
                _append_journal(log_file, f"stopped pid {pid}")
                return {"service": unit.name, "chroot": chroot_name, "status": "stopped", "pid": pid, "log_file": str(log_file)}
            time.sleep(0.1)
        try:
            _append_journal(log_file, f"sending SIGKILL to process group {pid}")
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _unlink(pid_file)
        _append_journal(log_file, f"killed pid {pid}")
        return {"service": unit.name, "chroot": chroot_name, "status": "killed", "pid": pid, "log_file": str(log_file)}

    def status(self, unit_name: str, *, chroot: str | None = None) -> dict[str, Any]:
        unit = self.catalog.get(unit_name)
        chroot_name = self._bound_chroot(unit, requested=chroot)
        pid_file = self._pid_file(chroot_name, unit.name)
        pid = _read_pid(pid_file)
        base = {
            "service": unit.name,
            "chroot": chroot_name,
            "enabled": self.is_enabled(unit),
            "wanted_by": unit.wanted_by,
            "after": unit.after,
            "requires": unit.requires,
            "pid_file": str(pid_file),
            "log_file": str(self._log_file(chroot_name, unit.name)),
        }
        if pid is None:
            return {**base, "status": "stopped"}
        if _pid_running(pid):
            return {**base, "status": "running", "pid": pid}
        return {**base, "status": "stale", "pid": pid}

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
                        executor.submit(self._start_unit, graph[name], chroot=graph[name].chroot, foreground=False): name
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
                        row = self._start_unit(unit, chroot=unit.chroot, foreground=False)
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
        controller.mount()
        controller.fix_tty()
        if unit.x11:
            controller._prepare_x11_host()
        log_file = self._log_file(chroot, unit.name)
        service_user = "root" if unit.runs_as_root() else (unit.user or cfg.username)
        script_path = self._write_service_script(cfg, chroot, unit, service_user=service_user)
        _append_journal(log_file, f"starting {unit.name}.service in chroot={chroot} user={service_user}")
        _append_journal(log_file, f"ExecStart: {unit.exec_start}")
        _append_journal(log_file, f"ServiceScript: {script_path}")
        if foreground:
            argv, env = controller.service_invocation(root=unit.runs_as_root(), command=str(script_path), x11=unit.x11, username=unit.user)
            result = self.context.runner.run(argv, check=False, env=env, chroot_env=True, capture_output=False)
            code = result.returncode
            _append_journal(log_file, f"foreground process exited returncode={code}")
            return {"service": unit.name, "chroot": chroot, "status": "exited", "returncode": code, "log_file": str(log_file)}
        argv, env = controller.service_invocation(root=unit.runs_as_root(), command=str(script_path), x11=unit.x11, username=unit.user)
        pid = self.context.runner.spawn(argv, env=env, chroot_env=True, stdout_path=log_file)
        pid_file = self._pid_file(chroot, unit.name)
        if not self.context.runner.dry_run:
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(f"{pid}\n", encoding="utf-8")
        _append_journal(log_file, f"spawned pid={pid}")
        return {"service": unit.name, "chroot": chroot, "status": "started", "pid": pid, "pid_file": str(pid_file), "log_file": str(log_file)}

    def _write_service_script(self, cfg: ChrootConfig, chroot: str, unit: ServiceUnit, *, service_user: str) -> str:
        script_dir = cfg.chroot_base / "tmp" / "chrootctl-services"
        script_name = f"{_safe_name(chroot)}-{_safe_name(unit.name)}.sh"
        script_path = script_dir / script_name
        chroot_script_path = f"/tmp/chrootctl-services/{script_name}"
        if self.context.runner.dry_run:
            return chroot_script_path
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text(_service_script_text(unit, service_user=service_user), encoding="utf-8")
        script_path.chmod(0o755)
        return chroot_script_path

    def _bound_chroot(self, unit: ServiceUnit, *, requested: str | None) -> str:
        if not unit.chroot:
            raise RuntimeError(f"service {unit.name} is not bound to a chroot; add [Service] Chroot=<name>")
        if requested and requested != unit.chroot:
            raise RuntimeError(f"service {unit.name} is bound to chroot {unit.chroot}; requested {requested}")
        return unit.chroot

    def _pid_file(self, chroot: str, unit_name: str) -> Path:
        return self.context.config.service_state_dir / f"{_safe_name(chroot)}-{_safe_name(unit_name)}.pid"

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
        restart=_get(service, "Restart", "no") or "no",
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
    lines.extend(
        [
            "echo \"[chrootctl-service] exec cwd=$(pwd 2>/dev/null || true) home=${HOME:-}\"",
            "echo '[chrootctl-service] ===== exec ====='",
            f"exec {unit.exec_start}",
            "",
        ]
    )
    return "\n".join(lines)


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
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
