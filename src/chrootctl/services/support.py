from __future__ import annotations

import gzip
import io
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from ..models import SupportBundleResult
from .context import ServiceContainer
from .storage_safety import require_contained
from .transfer import managed_transfer_archive, managed_transfer_root

_MAX_LOG_BYTES = 256 * 1024
_MAX_LOG_LINES = 2000
_MAX_JOB_LOG_LINES = 400
_MAX_JOB_LOG_BYTES = 128 * 1024
_MAX_JSON_BYTES = 512 * 1024
_MAX_SUPPORT_UNCOMPRESSED_BYTES = 4 * 1024 * 1024
_MAX_TEXT = 16 * 1024
_SECRET_KEY = re.compile(r"(?i)(password|passwd|token|secret|authorization|cookie|api[_-]?key|private[_-]?key|credential)")
_SECRET_TEXT = re.compile(
    r"(?i)\b(password|passwd|token|secret|authorization|api[_-]?key|cookie)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_CLI_SECRET = re.compile(r"(?i)(--(?:password|passwd|token|secret|api-key|api_key)\s+)([^\s]+)")
_URL_CREDENTIAL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^/@:\s]+:)([^@/\s]+)(@)")
_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----", re.DOTALL)


class SupportService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def export_bundle(self, archive: Path | None = None, *, jobs=None, extra_json: dict[str, Any] | None = None) -> SupportBundleResult:
        root = managed_transfer_root().resolve()
        requested = (archive or managed_transfer_archive("chrootctl-support-bundle", "tar.gz")).expanduser()
        if archive is not None and requested.is_symlink():
            raise RuntimeError("support bundle destination must not be a symlink")
        target = require_contained(
            root,
            requested.resolve(),
            label="support bundle artifact",
        )
        if target == root or target.suffixes[-2:] != [".tar", ".gz"]:
            raise RuntimeError("support bundle destination must be a managed .tar.gz file")
        if target.exists() and (target.is_symlink() or not target.is_file()):
            raise RuntimeError(f"refusing unsafe support bundle destination: {target}")

        replacements = self._path_replacements()
        files: dict[str, bytes] = {}
        manifest = {
            "schemaVersion": 2,
            "sanitized": True,
            "paths": {
                "config": "$CONFIG",
                "database": "$DATABASE",
                "log": "$LOG",
                "chrootRoot": "$CHROOT_ROOT",
                "termuxHome": "$TERMUX_HOME",
                "termuxPrefix": "$TERMUX_PREFIX",
            },
            "jobCount": len(jobs.list_recent(limit=20)) if jobs is not None else 0,
            "limits": {"logBytes": _MAX_LOG_BYTES, "logLines": _MAX_LOG_LINES, "jobLogLines": _MAX_JOB_LOG_LINES},
        }
        files["manifest.json"] = self._json_bytes(manifest, replacements)

        events = [event.to_display_dict() for event in self.services.audit().recent(limit=100)]
        files["events.json"] = self._json_bytes(events, replacements)

        doctor = self.services.system().host_doctor()
        if isinstance(doctor, dict):
            checks = doctor.get("checks", [])
            advisories = doctor.get("advisories", [])
        else:
            checks = doctor
            advisories = []
        files["doctor-host.json"] = self._json_bytes(
            {"checks": [row.to_display_dict() for row in checks], "advisories": advisories}, replacements
        )

        registry_rows = [row.to_display_dict() for row in self.services.chroots().list()]
        files["chroots.json"] = self._json_bytes(registry_rows, replacements)

        config_payload = {
            "distroName": self.services.base_config.distro_name,
            "username": self.services.base_config.username,
            "targetArch": self.services.base_config.target_arch,
            "chrootRoot": "$CHROOT_ROOT",
            "termuxHome": "$TERMUX_HOME",
            "termuxPrefix": "$TERMUX_PREFIX",
            "logFile": "$LOG",
            "databasePath": "$DATABASE",
        }
        files["config-sanitized.json"] = self._json_bytes(config_payload, replacements)

        if jobs is not None:
            job_rows = []
            for job in jobs.list_recent(limit=25):
                payload = job.to_event_payload(log_download_url="")
                payload.pop("log_download_url", None)
                payload["log_lines"] = self._bounded_lines(list(job.log_lines), _MAX_JOB_LOG_LINES, _MAX_JOB_LOG_BYTES)
                job_rows.append(payload)
            files["jobs.json"] = self._json_bytes(job_rows, replacements)

        if extra_json:
            for name, value in sorted(extra_json.items()):
                entry = str(name).strip().replace("\\", "/")
                parts = Path(entry).parts
                if not entry.endswith(".json") or not parts or entry.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                    raise RuntimeError(f"invalid support evidence entry name: {name!r}")
                files[entry] = self._json_bytes(value, replacements)

        log_text = self._bounded_log(self.services.base_config.log_file.expanduser())
        if log_text:
            files["logs/chrootctl.log"] = self._redact_text(log_text, replacements).encode("utf-8")

        manifest["limits"]["jsonBytes"] = _MAX_JSON_BYTES
        manifest["limits"]["bundleUncompressedBytes"] = _MAX_SUPPORT_UNCOMPRESSED_BYTES
        files["manifest.json"] = self._json_bytes(manifest, replacements)
        total_uncompressed = sum(len(data) for data in files.values())
        if total_uncompressed > _MAX_SUPPORT_UNCOMPRESSED_BYTES:
            raise RuntimeError(f"support evidence exceeds bounded size limit: {total_uncompressed} bytes")

        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(root))
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with tmp.open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w") as tf:
                        for name in sorted(files):
                            data = files[name]
                            info = tarfile.TarInfo(name=name)
                            info.size = len(data)
                            info.mode = 0o600
                            info.uid = 0
                            info.gid = 0
                            info.uname = "root"
                            info.gname = "root"
                            info.mtime = 0
                            tf.addfile(info, io.BytesIO(data))
                raw.flush()
                os.fsync(raw.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

        included = tuple(sorted(files))
        registered = self.services.transfer().register_artifact(target, kind="support-bundle", metadata={"sanitized": True, "bounded": True})
        if registered is None:
            raise RuntimeError("support bundle could not be registered as a managed artifact")
        self.services.audit().record(
            "support-bundle.export",
            target=target.name,
            message="Sanitized managed support bundle exported",
            metadata={"included": str(len(included)), "bytes": str(target.stat().st_size)},
        )
        return SupportBundleResult(archive=target, included=included)

    def _path_replacements(self) -> tuple[tuple[str, str], ...]:
        config = self.services.base_config
        pairs = (
            (str(config.config_path()), "$CONFIG"),
            (str(config.database_path), "$DATABASE"),
            (str(config.log_file), "$LOG"),
            (str(config.chroot_root), "$CHROOT_ROOT"),
            (str(config.termux_home), "$TERMUX_HOME"),
            (str(config.termux_prefix), "$TERMUX_PREFIX"),
        )
        return tuple(sorted(((source, label) for source, label in pairs if source), key=lambda item: len(item[0]), reverse=True))

    def _json_bytes(self, value: Any, replacements: tuple[tuple[str, str], ...]) -> bytes:
        redacted = self._redact_value(value, replacements)
        encoded = (json.dumps(redacted, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        if len(encoded) <= _MAX_JSON_BYTES:
            return encoded
        preview = encoded[: min(_MAX_TEXT, _MAX_JSON_BYTES // 2)].decode("utf-8", errors="replace")
        bounded = {"truncated": True, "originalBytes": len(encoded), "preview": preview}
        return (json.dumps(bounded, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

    def _redact_value(self, value: Any, replacements: tuple[tuple[str, str], ...], *, key: str = "") -> Any:
        if _SECRET_KEY.search(key):
            return "<redacted>"
        if isinstance(value, dict):
            return {str(k): self._redact_value(v, replacements, key=str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact_value(item, replacements, key=key) for item in value]
        if isinstance(value, str):
            return self._redact_text(value, replacements)
        return value

    @staticmethod
    def _redact_text(text: str, replacements: tuple[tuple[str, str], ...]) -> str:
        value = text[:_MAX_TEXT] + ("…<truncated>" if len(text) > _MAX_TEXT else "")
        for source, label in replacements:
            value = value.replace(source, label)
        value = _PRIVATE_KEY_BLOCK.sub("<redacted-private-key>", value)
        value = _SECRET_TEXT.sub(lambda match: f"{match.group(1)}=<redacted>", value)
        value = _BEARER.sub("Bearer <redacted>", value)
        value = _CLI_SECRET.sub(lambda match: f"{match.group(1)}<redacted>", value)
        value = _URL_CREDENTIAL.sub(lambda match: f"{match.group(1)}<redacted>{match.group(3)}", value)
        return value

    @staticmethod
    def _bounded_lines(lines: list[str], max_lines: int, max_bytes: int) -> list[str]:
        selected: list[str] = []
        used = 0
        for raw in reversed(lines[-max_lines:]):
            line = str(raw)[:_MAX_TEXT]
            size = len((line + "\n").encode("utf-8", errors="replace"))
            if selected and used + size > max_bytes:
                break
            if size > max_bytes:
                line = line.encode("utf-8", errors="replace")[-max_bytes:].decode("utf-8", errors="replace")
                size = len(line.encode("utf-8", errors="replace"))
            selected.append(line)
            used += size
        selected.reverse()
        return selected

    @staticmethod
    def _bounded_log(path: Path) -> str:
        if not path.is_file() or path.is_symlink():
            return ""
        try:
            with path.open("rb") as handle:
                size = path.stat().st_size
                if size > _MAX_LOG_BYTES:
                    handle.seek(-_MAX_LOG_BYTES, os.SEEK_END)
                data = handle.read(_MAX_LOG_BYTES)
        except OSError:
            return ""
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()[-_MAX_LOG_LINES:]
        return "\n".join(lines) + ("\n" if lines else "")
