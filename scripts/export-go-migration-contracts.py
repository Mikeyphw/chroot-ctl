#!/usr/bin/env python3
"""Export deterministic Python compatibility contracts for the Go migration.

This script is intentionally temporary migration tooling. It freezes public and
persisted behavior before the Python implementation is replaced. The generated
JSON is consumed by Go tests and by Python drift tests during the transition.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import inspect
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from chrootctl import __version__  # noqa: E402
from chrootctl import config as config_mod  # noqa: E402
from chrootctl import models as models_mod  # noqa: E402
from chrootctl import validation as validation_mod  # noqa: E402
from chrootctl.bridge import protocol as bridge_protocol  # noqa: E402
from chrootctl.bridge import redaction as bridge_redaction  # noqa: E402
from chrootctl.bridge.cli import build_parser as build_bridge_parser  # noqa: E402
from chrootctl.bridge.registry import SPECS, _PAYLOAD_FIELDS  # noqa: E402
from chrootctl.config import (  # noqa: E402
    ANDROID_STATE_ROOT,
    DEFAULT_DNS_SERVERS,
    DEFAULT_MEDIA_MOUNTS,
    LEGACY_TERMUX_HOME,
    ChrootConfig,
)
from chrootctl.errors import AppError, error_from_http_exception  # noqa: E402
from chrootctl.logging_utils import configure_logging  # noqa: E402
from chrootctl.magisk import (  # noqa: E402
    ANDROID_APP_VERSION_CODE,
    BACKEND_IMPLEMENTATION,
    BACKEND_VERSION,
    ANDROID_APP_VERSION_NAME,
    BRIDGE_PROTOCOL_VERSION,
    DEFAULT_MODULE_ID,
    DEFAULT_MODULE_VERSION,
    DEFAULT_MODULE_VERSION_CODE,
    NATIVE_RUNTIME_ENTRYPOINT_PATH,
    NATIVE_RUNTIME_MANIFEST_PATH,
    PYTHON_PACKAGE_VERSION,
)
from chrootctl.native_runtime import (  # noqa: E402
    DEFAULT_NATIVE_RUNTIME_ABI,
    DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
    NATIVE_RUNTIME_KIND,
    NATIVE_RUNTIME_PLATFORM,
    NATIVE_RUNTIME_SCHEMA_VERSION,
)
from chrootctl.operations.models import (  # noqa: E402
    ACTIVE_STATES,
    OPERATION_SCHEMA_VERSION,
    TERMINAL_STATES,
    OperationRecord,
)
from chrootctl.parser import build_parser  # noqa: E402
from chrootctl.registry import SCHEMA  # noqa: E402
from chrootctl.release_parity import COMPATIBILITY_SCHEMA_VERSION  # noqa: E402

CONTRACT_DIR = REPO_ROOT / "migration" / "contracts" / "v1"
CONTRACT_SCHEMA_VERSION = 1


def _json_safe(value: Any) -> Any:
    if value is argparse.SUPPRESS:
        return "<SUPPRESS>"
    if value is dataclasses.MISSING:
        return "<MISSING>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return [_json_safe(item) for item in sorted(value, key=lambda item: str(item))]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _action_contract(action: argparse.Action) -> dict[str, Any]:
    action_type = action.__class__.__name__
    type_name = None
    if getattr(action, "type", None) is not None:
        type_value = action.type
        type_name = getattr(type_value, "__name__", str(type_value))
    choices = getattr(action, "choices", None)
    if isinstance(action, argparse._SubParsersAction):
        choices = sorted(action.choices)
    elif choices is not None:
        choices = list(choices)
    return {
        "dest": action.dest,
        "optionStrings": list(action.option_strings),
        "required": bool(getattr(action, "required", False)),
        "nargs": _json_safe(action.nargs),
        "default": _json_safe(action.default),
        "const": _json_safe(getattr(action, "const", None)),
        "choices": _json_safe(choices),
        "type": type_name,
        "action": action_type,
        "help": _json_safe(getattr(action, "help", None)),
        "metavar": _json_safe(getattr(action, "metavar", None)),
    }


def _parser_node(parser: argparse.ArgumentParser, path: tuple[str, ...]) -> dict[str, Any]:
    actions = [
        _action_contract(action)
        for action in parser._actions
        if not isinstance(action, argparse._HelpAction)
        and not isinstance(action, argparse._SubParsersAction)
    ]
    return {
        "path": list(path),
        "command": " ".join(path),
        "prog": parser.prog,
        "description": parser.description,
        "epilog": parser.epilog,
        "arguments": actions,
    }


def _walk_parser(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, subparser in action.choices.items():
            path = (*prefix, name)
            nodes.append(_parser_node(subparser, path))
            nodes.extend(_walk_parser(subparser, path))
    return nodes


def cli_contract() -> dict[str, Any]:
    parser = build_parser()
    bridge_parser = build_bridge_parser()
    main_nodes = _walk_parser(parser)
    bridge_nodes = _walk_parser(bridge_parser, ("app",))
    return {
        "contractSchemaVersion": CONTRACT_SCHEMA_VERSION,
        "pythonBackendVersion": __version__,
        "program": parser.prog,
        "description": parser.description,
        "globalArguments": [
            _action_contract(action)
            for action in parser._actions
            if not isinstance(action, argparse._HelpAction)
            and not isinstance(action, argparse._SubParsersAction)
        ],
        "commandNodeCount": len(main_nodes),
        "commandNodes": main_nodes,
        "appBridgeCommandNodeCount": len(bridge_nodes),
        "appBridgeCommandNodes": bridge_nodes,
    }


def bridge_contract() -> dict[str, Any]:
    operations = []
    for spec in SPECS.values():
        operations.append(
            {
                **spec.capability(),
                "payloadFields": sorted(_PAYLOAD_FIELDS.get(spec.name, frozenset())),
            }
        )
    return {
        "contractSchemaVersion": CONTRACT_SCHEMA_VERSION,
        "protocolVersion": bridge_protocol.PROTOCOL_VERSION,
        "operationCount": len(operations),
        "operations": operations,
        "request": {
            "maxBytes": bridge_protocol.MAX_BRIDGE_REQUEST_BYTES,
            "maxJsonDepth": bridge_protocol.MAX_BRIDGE_JSON_DEPTH,
            "maxStringLength": bridge_protocol.MAX_BRIDGE_STRING_LENGTH,
            "maxArrayLength": bridge_protocol.MAX_BRIDGE_ARRAY_LENGTH,
            "maxObjectKeys": bridge_protocol.MAX_BRIDGE_OBJECT_KEYS,
            "topLevelKeys": sorted(bridge_protocol._REQUEST_TOP_LEVEL_KEYS),
            "requestIdPattern": bridge_protocol._REQUEST_ID_RE.pattern,
            "operationPattern": bridge_protocol._OPERATION_RE.pattern,
            "previewContractFields": ["payloadHash", "previewId", "resourceRevision"],
        },
        "responseFields": ["protocolVersion", "requestId", "ok", "data", "error", "warnings", "nextSteps"],
        "transports": ["json", "ndjson"],
        "arbitraryShell": False,
        "redaction": {
            "secretKeys": sorted(bridge_redaction._SECRET_KEYS),
            "bearerPattern": bridge_redaction._BEARER_RE.pattern,
            "secretAssignmentPattern": bridge_redaction._SECRET_ASSIGNMENT_RE.pattern,
            "opensslPassPattern": bridge_redaction._OPENSSL_PASS_RE.pattern,
        },
    }


def _dataclass_field_contract(field: dataclasses.Field[Any]) -> dict[str, Any]:
    if field.default is not dataclasses.MISSING:
        default: Any = _json_safe(field.default)
        default_kind = "value"
    elif field.default_factory is not dataclasses.MISSING:  # type: ignore[comparison-overlap]
        factory = field.default_factory
        default = getattr(factory, "__name__", str(factory))
        default_kind = "factory"
    else:
        default = None
        default_kind = "required"
    return {
        "name": field.name,
        "type": str(field.type),
        "defaultKind": default_kind,
        "default": default,
    }


def persistence_contract() -> dict[str, Any]:
    config_fields = [_dataclass_field_contract(field) for field in dataclasses.fields(ChrootConfig)]
    operation_fields = [_dataclass_field_contract(field) for field in dataclasses.fields(OperationRecord)]
    return {
        "contractSchemaVersion": CONTRACT_SCHEMA_VERSION,
        "sqlite": {
            "schemaSql": SCHEMA.strip() + "\n",
            "pragmas": {
                "busy_timeout": 5000,
                "foreign_keys": "ON",
                "journal_mode": "WAL",
                "synchronous": "FULL",
                "connectTimeoutSeconds": 5.0,
            },
            "databaseBasename": "chroots.sqlite3",
        },
        "operations": {
            "schemaVersion": OPERATION_SCHEMA_VERSION,
            "activeStates": sorted(ACTIVE_STATES),
            "terminalStates": sorted(TERMINAL_STATES),
            "recordFields": operation_fields,
            "jsonFields": list(OperationRecord("id", "kind", "title").to_dict().keys()),
            "recordPattern": "<operationId>.json",
            "eventPattern": "<operationId>.events.jsonl",
            "cancelPattern": "<operationId>.cancel",
        },
        "config": {
            "androidStateRoot": str(ANDROID_STATE_ROOT),
            "legacyTermuxHome": str(LEGACY_TERMUX_HOME),
            "androidConfigPath": str(ANDROID_STATE_ROOT / "config.json"),
            "androidDatabasePath": str(ANDROID_STATE_ROOT / "chroots.sqlite3"),
            "androidSnapshotDir": str(ANDROID_STATE_ROOT / "snapshots"),
            "defaultDnsServers": list(DEFAULT_DNS_SERVERS),
            "defaultMediaMounts": dict(DEFAULT_MEDIA_MOUNTS),
            "fields": config_fields,
        },
    }



def _call_contract(function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        value = function(*args, **kwargs)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "errorType": type(exc).__name__, "error": str(exc)}
    return {"ok": True, "value": _json_safe(value)}


def _config_payload(cfg: ChrootConfig) -> dict[str, Any]:
    return {
        "chroot_root": str(cfg.chroot_root),
        "distro_name": cfg.distro_name,
        "username": cfg.username,
        "target_arch": cfg.target_arch,
        "termux_home": str(cfg.termux_home),
        "termux_prefix": str(cfg.termux_prefix),
        "log_file": str(cfg.log_file),
        "database_path": str(cfg.database_path),
        "shell_path": cfg.shell_path,
        "mount_data_with_dev_suid": cfg.mount_data_with_dev_suid,
        "dev_shm_size": cfg.dev_shm_size,
        "media_mounts": [dataclasses.asdict(item) for item in cfg.media_mounts],
        "extra_bind_mounts": [dataclasses.asdict(item) for item in cfg.extra_bind_mounts],
        "extra_packages": list(cfg.extra_packages),
        "locale": cfg.locale,
        "dns_servers": list(cfg.dns_servers),
        "post_install_hooks": list(cfg.post_install_hooks),
        "install_profile": cfg.install_profile,
        "snapshot_dir": str(cfg.snapshot_dir),
        "snapshot_before_destructive": cfg.snapshot_before_destructive,
        "tool_manifest_dirs": [str(item) for item in cfg.tool_manifest_dirs],
        "tool_script_dirs": [str(item) for item in cfg.tool_script_dirs],
        "addon_manifest_dirs": [str(item) for item in cfg.addon_manifest_dirs],
        "addon_script_dirs": [str(item) for item in cfg.addon_script_dirs],
        "service_dirs": [str(item) for item in cfg.service_dirs],
        "service_state_dir": str(cfg.service_state_dir),
        "service_log_dir": str(cfg.service_log_dir),
        "chroot_overrides": _json_safe(cfg.chroot_overrides),
        "derived": {
            "chroot_base": str(cfg.chroot_base),
            "user_home_in_chroot": str(cfg.user_home_in_chroot),
            "termux_home_in_chroot": str(cfg.termux_home_in_chroot),
        },
    }


def _config_defaults_for(*, android: bool, home: Path) -> dict[str, Any]:
    original_runtime = config_mod.is_android_runtime
    original_home = config_mod.Path.home
    try:
        config_mod.is_android_runtime = lambda: android
        config_mod.Path.home = classmethod(lambda cls: home)
        cfg = ChrootConfig()
        result = _config_payload(cfg)
        result["default_config_path"] = str(ChrootConfig.default_config_path())
        return result
    finally:
        config_mod.is_android_runtime = original_runtime
        config_mod.Path.home = original_home


def _model_field_contracts() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, value in inspect.getmembers(models_mod, inspect.isclass):
        if value.__module__ != models_mod.__name__ or not dataclasses.is_dataclass(value):
            continue
        result[name] = [field.name for field in dataclasses.fields(value)]
    return dict(sorted(result.items()))


def _logging_contract() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chrootctl.log"
        logger = configure_logging(path, verbose=False)
        normal = {
            "loggerName": logger.name,
            "loggerLevel": logging.getLevelName(logger.level),
            "propagate": logger.propagate,
            "handlers": [
                {
                    "type": type(handler).__name__,
                    "level": logging.getLevelName(handler.level),
                    "format": handler.formatter._fmt if handler.formatter else None,
                }
                for handler in logger.handlers
            ],
        }
        for handler in list(logger.handlers):
            handler.close()
        logger.handlers.clear()
        verbose = configure_logging(path, verbose=True)
        verbose_console_level = logging.getLevelName(verbose.handlers[0].level)
        for handler in list(verbose.handlers):
            handler.close()
        verbose.handlers.clear()
    normal["verboseConsoleLevel"] = verbose_console_level
    return normal


def foundations_contract() -> dict[str, Any]:
    custom_base = ChrootConfig(
        database_path=Path("/tmp/base/chroots.sqlite3"),
        snapshot_dir=Path("/tmp/base/snapshots"),
        service_dirs=(Path("/tmp/base/services"),),
        service_state_dir=Path("/tmp/base/run/services"),
        service_log_dir=Path("/tmp/base/logs/services"),
    )
    custom_payload = {
        "mount_data_with_dev_suid": False,
        "dev_shm_size": "64M",
        "media_mounts": {
            "/storage/shared": {"target": "mnt/shared", "read_only": True},
        },
        "extra_bind_mounts": [
            {"source": "/srv/cache", "target": "var/cache/shared", "enabled": True},
        ],
        "extra_packages": ["htop"],
        "locale": "pt_BR.UTF-8",
        "dns_servers": ["9.9.9.9"],
        "post_install_hooks": ["echo done"],
        "repositories": {
            "tool_manifests": ["/tmp/repo/tools"],
            "addon_scripts": ["/tmp/repo/addons/scripts"],
        },
        "chroot_overrides": {
            "work": {"extra_packages": ["git-lfs"], "install_profile": "dev"},
        },
    }
    kwargs = ChrootConfig._kwargs_from_payload(custom_payload, custom_base)
    custom = custom_base.with_overrides(**kwargs).with_overrides(
        chroot_overrides=dict(custom_payload["chroot_overrides"])
    )
    work = custom.for_chroot("work")

    op = models_mod.OperationResult()
    op.add_success()
    op.add_failure("boom")
    op.add_skipped()
    session = models_mod.SessionActionResult("restart", "androidos", 0, ("inspect logs",))
    log_snapshot = models_mod.LogSnapshot(
        Path("/tmp/chrootctl.log"),
        "INFO",
        ("fallback",),
        entries=(models_mod.LogEntry("line one", "INFO"), models_mod.LogEntry("line two", "WARN")),
    )
    app_build = models_mod.AppBuildResult("module.zip", Path("/tmp/module.zip"), Path("/tmp"), ("androidos",))

    app_error = AppError(
        code="config_invalid",
        title="Invalid configuration",
        message="The configuration is invalid.",
        details={"field": "username"},
        hints=["Use a lowercase username."],
        actions=[{"label": "Open docs", "href": "https://example.invalid/docs"}],
        retryable=False,
        status_code=422,
    )

    validation_cases = [
        ("validate_chroot_name", validation_mod.validate_chroot_name, ("androidos",), {}),
        ("validate_chroot_name_invalid_path", validation_mod.validate_chroot_name, ("../bad",), {}),
        ("validate_chroot_name_non_string", validation_mod.validate_chroot_name, (7,), {}),
        ("validate_snapshot_name", validation_mod.validate_snapshot_name, ("pre-upgrade_1",), {}),
        ("validate_catalog_name", validation_mod.validate_catalog_name, ("desktop.dev",), {}),
        ("validate_service_name", validation_mod.validate_service_name, ("sshd@work.service:unit",), {}),
        ("validate_username", validation_mod.validate_username, ("mike",), {}),
        ("validate_username_invalid", validation_mod.validate_username, ("Mike",), {}),
        ("strict_bool", validation_mod.strict_bool, (False,), {"field": "enabled"}),
        ("strict_bool_integer", validation_mod.strict_bool, (1,), {"field": "enabled"}),
        ("bounded_int", validation_mod.bounded_int, (3,), {"field": "limit", "minimum": 1, "maximum": 5}),
        ("bounded_int_bool", validation_mod.bounded_int, (True,), {"field": "limit", "minimum": 1, "maximum": 5}),
        ("bounded_int_range", validation_mod.bounded_int, (9,), {"field": "limit", "minimum": 1, "maximum": 5}),
        ("strict_string_list", validation_mod.strict_string_list, ([" a ", "", "b"],), {"field": "items"}),
        ("strict_string_list_invalid", validation_mod.strict_string_list, (["a", 2],), {"field": "items"}),
        ("unique_catalog_names", validation_mod.unique_catalog_names, (["one", "two"],), {}),
        ("unique_catalog_names_duplicate", validation_mod.unique_catalog_names, (["one", "one"],), {}),
        ("relative_path", validation_mod.validate_relative_chroot_path, ("home/mike",), {}),
        ("relative_path_normalized_input", validation_mod.validate_relative_chroot_path, ("a/./b",), {}),
        ("relative_path_parent", validation_mod.validate_relative_chroot_path, ("a/../b",), {}),
        ("relative_path_absolute", validation_mod.validate_relative_chroot_path, ("/root",), {}),
        ("safe_archive_name", validation_mod.validate_safe_archive_name, ("backup.tar.zst",), {}),
        ("safe_archive_name_multiline", validation_mod.validate_safe_archive_name, ("bad" + chr(10) + "name",), {}),
    ]

    return {
        "contractSchemaVersion": CONTRACT_SCHEMA_VERSION,
        "models": {
            "fieldNames": _model_field_contracts(),
            "samples": {
                "operationResult": {
                    "state": dataclasses.asdict(op),
                    "display": op.to_display_dict(),
                },
                "sessionAction": {
                    "success": session.success,
                    "display": session.to_display_dict(),
                },
                "logSnapshot": {
                    "text": log_snapshot.text,
                    "display": log_snapshot.to_display_dict(),
                },
                "appBuild": {
                    "nextSteps": list(app_build.next_steps),
                    "display": app_build.to_display_dict(),
                },
            },
        },
        "validation": {
            "cases": [
                {"name": name, **_call_contract(function, *args, **kwargs)}
                for name, function, args, kwargs in validation_cases
            ],
        },
        "config": {
            "defaultNonAndroid": _config_defaults_for(android=False, home=Path("/home/tester")),
            "defaultAndroid": _config_defaults_for(android=True, home=Path("/home/tester")),
            "customPayload": _json_safe(custom_payload),
            "customResolved": _config_payload(custom),
            "workResolved": _config_payload(work),
            "shellResolution": {
                "configured": custom.resolved_shell({custom.shell_path: True}),
                "bashFallback": custom.resolved_shell({"/bin/bash": True}),
                "configuredFallback": custom.resolved_shell({}),
            },
        },
        "errors": {
            "appError": app_error.to_response().to_http_payload(),
            "http404": error_from_http_exception(404, None).to_http_payload(),
            "http422": error_from_http_exception(
                422,
                {
                    "code": "bad_request",
                    "message": "bad payload",
                    "details": {"field": "name"},
                    "hints": ["Pick another name."],
                    "actions": [{"label": "Retry", "command": "chrootctl status"}],
                    "retryable": True,
                },
            ).to_http_payload(),
        },
        "logging": _logging_contract(),
    }

def release_contract() -> dict[str, Any]:
    return {
        "contractSchemaVersion": CONTRACT_SCHEMA_VERSION,
        "bridgeProtocolVersion": BRIDGE_PROTOCOL_VERSION,
        "compatibilitySchemaVersion": COMPATIBILITY_SCHEMA_VERSION,
        "nativeRuntime": {
            "schemaVersion": NATIVE_RUNTIME_SCHEMA_VERSION,
            "kind": NATIVE_RUNTIME_KIND,
            "platform": NATIVE_RUNTIME_PLATFORM,
            "abi": DEFAULT_NATIVE_RUNTIME_ABI,
            "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
            "manifestPath": NATIVE_RUNTIME_MANIFEST_PATH.as_posix(),
            "entrypointPath": NATIVE_RUNTIME_ENTRYPOINT_PATH.as_posix(),
        },
        "backend": {"implementation": BACKEND_IMPLEMENTATION, "version": BACKEND_VERSION},
        "module": {
            "id": DEFAULT_MODULE_ID,
            "version": DEFAULT_MODULE_VERSION,
            "versionCode": DEFAULT_MODULE_VERSION_CODE,
        },
        "androidApp": {
            "applicationId": "com.mikeyphw.chrootctl",
            "versionName": ANDROID_APP_VERSION_NAME,
            "versionCode": ANDROID_APP_VERSION_CODE,
        },
    }


def contracts() -> dict[str, dict[str, Any]]:
    return {
        "cli.json": cli_contract(),
        "bridge.json": bridge_contract(),
        "persistence.json": persistence_contract(),
        "foundations.json": foundations_contract(),
        "release.json": release_contract(),
    }


def _encoded(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_contracts() -> None:
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in contracts().items():
        (CONTRACT_DIR / name).write_text(_encoded(payload), encoding="utf-8")


def check_contracts() -> list[str]:
    mismatches: list[str] = []
    for name, payload in contracts().items():
        path = CONTRACT_DIR / name
        expected = _encoded(payload)
        try:
            actual = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            mismatches.append(f"missing {path.relative_to(REPO_ROOT)}")
            continue
        if actual != expected:
            digest_expected = hashlib.sha256(expected.encode()).hexdigest()[:12]
            digest_actual = hashlib.sha256(actual.encode()).hexdigest()[:12]
            mismatches.append(
                f"stale {path.relative_to(REPO_ROOT)} (expected sha256:{digest_expected}, got sha256:{digest_actual})"
            )
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed fixtures do not match the Python implementation.")
    args = parser.parse_args()
    if args.check:
        mismatches = check_contracts()
        if mismatches:
            for mismatch in mismatches:
                print(mismatch, file=sys.stderr)
            return 1
        print("Go migration contracts are current.")
        return 0
    write_contracts()
    print(f"Wrote {len(contracts())} contract files under {CONTRACT_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
