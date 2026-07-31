from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from ..operations.manager import detach_process_group
from ..services import create_service_container
from .dispatcher import BridgeDispatcher
from .events import ndjson_sink
from .protocol import BridgeProtocolError, BridgeRequest, BridgeResponse


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        services = create_service_container(args.config, dry_run=args.dry_run, verbose=args.verbose)
        dispatcher = BridgeDispatcher(services)
        if args.command == "capabilities":
            _write_json(BridgeResponse.success("capabilities", dispatcher.capabilities()).to_dict())
            return 0
        if args.command == "state":
            response = dispatcher.state()
            _write_json(response.to_dict())
            return 0 if response.ok else 2
        if args.command in {"query", "preview", "run"}:
            request = BridgeRequest.from_json(_read_request(args.request_file))
            if args.command == "query":
                response = dispatcher.query(request)
                _write_json(response.to_dict())
                return 0 if response.ok else 2
            if args.command == "preview":
                response = dispatcher.preview(request)
                _write_json(response.to_dict())
                return 0 if response.ok else 2
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
    except BridgeProtocolError as exc:
        _write_json(BridgeResponse.failure("unknown", exc).to_dict())
        return 2
    except Exception as exc:
        _write_json(BridgeResponse.failure("unknown", exc).to_dict())
        return 2
    parser.error("unsupported bridge command")
    return 2


def _read_request(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write_json(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
