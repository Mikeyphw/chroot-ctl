from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Sequence

from .protocol import BridgeProtocolError, BridgeRequest, BridgeResponse, MAX_BRIDGE_REQUEST_BYTES, PROTOCOL_VERSION, extract_request_id_safely


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chrootctl app", description="Versioned local bridge for the native Android app.")
    parser.add_argument("--config", type=Path, default=None, help="Optional chrootctl configuration file.")
    parser.add_argument("--dry-run", action="store_true", help="Use dry-run service execution where supported.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose backend logging.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("capabilities", help="Print bridge capabilities as JSON.")
    sub.add_parser("state", help="Print the native app bootstrap state as JSON.")

    for name in ("query", "preview", "run"):
        command = sub.add_parser(name, help=f"Execute a bridge {name} request.")
        command.add_argument("--request-file", default="-", help="JSON request file, or - for stdin.")
        if name == "run":
            command.add_argument("--events", choices=("ndjson",), default="ndjson", help="Streaming event encoding.")

    operation = sub.add_parser("operation", help="Read a persistent operation record.")
    operation.add_argument("operation_id")
    cancel = sub.add_parser("cancel", help="Request cancellation of a persistent operation.")
    cancel.add_argument("operation_id")
    reconcile = sub.add_parser("reconcile", help="Explicitly reconcile a persistent operation after transport/process loss.")
    reconcile.add_argument("operation_id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        raw_request: str | None = None
        if args.command == "capabilities":
            response = _capabilities_response(config_path=args.config)
            _write_json(response.to_dict())
            return 0

        from ..services import create_service_container
        from .dispatcher import BridgeDispatcher

        services = create_service_container(args.config, dry_run=args.dry_run, verbose=args.verbose)
        dispatcher = BridgeDispatcher(services)
        if args.command == "state":
            response = dispatcher.state()
            _write_json(response.to_dict())
            return 0 if response.ok else 2
        if args.command in {"query", "preview", "run"}:
            raw_request = _read_request(args.request_file)
            request = BridgeRequest.from_json(raw_request)
            if args.command == "query":
                response = dispatcher.query(request)
                _write_json(response.to_dict())
                return 0 if response.ok else 2
            if args.command == "preview":
                response = dispatcher.preview(request)
                _write_json(response.to_dict())
                return 0 if response.ok else 2
            from ..operations.manager import detach_process_group
            from .events import ndjson_sink

            detach_process_group()
            return dispatcher.run(request, ndjson_sink(sys.stdout))
        if args.command == "operation":
            response = dispatcher.operation(args.operation_id)
            _write_json(response.to_dict())
            return 0 if response.ok else 2
        if args.command == "cancel":
            response = dispatcher.cancel(args.operation_id)
            _write_json(response.to_dict())
            return 0 if response.ok else 2
        if args.command == "reconcile":
            response = dispatcher.reconcile(args.operation_id)
            _write_json(response.to_dict())
            return 0 if response.ok else 2
    except BridgeProtocolError as exc:
        _write_json(BridgeResponse.failure(_request_id_from_raw(locals().get("raw_request")), exc).to_dict())
        return 2
    except Exception as exc:
        _write_json(BridgeResponse.failure(_request_id_from_raw(locals().get("raw_request")), exc).to_dict())
        return 2
    parser.error("unsupported bridge command")
    return 2


def _capabilities_response(config_path: Path | None = None) -> BridgeResponse:
    warnings: list[str] = []
    next_steps: list[str] = []
    operations: list[dict[str, Any]] = []
    operation_root = _default_operation_root(config_path)
    runtime_health: dict[str, Any] = {"status": "ready"}
    try:
        from .registry import capabilities

        operations = capabilities()
    except Exception as exc:
        runtime_health = {
            "status": "degraded",
            "code": "CAPABILITIES_PARTIAL",
            "message": _safe_error_message(exc),
        }
        warnings.append("Bridge protocol responded, but operation metadata could not be fully loaded.")
        next_steps.append("Open Runtime diagnostics to inspect Python dependencies and module installation state.")
    return BridgeResponse.success(
        "capabilities",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "backendVersion": _backend_version(),
            "operations": operations,
            "operationRoot": operation_root,
            "transport": ["json", "ndjson"],
            "arbitraryShell": False,
            "runtimeHealth": runtime_health,
        },
        warnings=tuple(warnings),
        next_steps=tuple(next_steps),
    )


def _default_operation_root(config_path: Path | None) -> str:
    try:
        from ..config import ChrootConfig

        return str(ChrootConfig.load(config_path).database_path.parent / "operations")
    except Exception:
        return "/data/adb/chrootctl/operations"


def _backend_version() -> str:
    try:
        return version("chrootctl")
    except PackageNotFoundError:
        pass
    except Exception:
        pass
    try:
        from .. import __version__

        return __version__
    except Exception:
        return "unknown"


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return " ".join(message.split())[:240]


def _read_request(path: str) -> str:
    if path == "-":
        data = sys.stdin.buffer.read(MAX_BRIDGE_REQUEST_BYTES + 1)
        if len(data) > MAX_BRIDGE_REQUEST_BYTES:
            raise BridgeProtocolError("REQUEST_TOO_LARGE", f"Bridge request must not exceed {MAX_BRIDGE_REQUEST_BYTES} bytes")
        return data.decode("utf-8")
    request_path = Path(path)
    try:
        if request_path.stat().st_size > MAX_BRIDGE_REQUEST_BYTES:
            raise BridgeProtocolError("REQUEST_TOO_LARGE", f"Bridge request must not exceed {MAX_BRIDGE_REQUEST_BYTES} bytes")
    except FileNotFoundError:
        raise
    return request_path.read_text(encoding="utf-8")


def _request_id_from_raw(raw: object) -> str:
    if isinstance(raw, str):
        return extract_request_id_safely(raw) or "unknown"
    return "unknown"


def _write_json(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
