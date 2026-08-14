
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import os
from pathlib import Path
from typing import Literal

import yaml

from .config import ChrootConfig
from .interactive import Choice, select_many
from .models import CatalogApplyResult
from .registry import ChrootRegistry
from .system import SystemRunner
from .user_sync import UserSyncManager

SUPPORTED_DISTROS = {"ubuntu", "arch"}
CATALOG_KIND = Literal["tool", "addon"]
SUPPORTED_SCRIPT_SUFFIXES = {".sh", ".py"}


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    kind: CATALOG_KIND
    name: str
    description: str
    distros: tuple[str, ...]
    categories: tuple[str, ...]
    script: str
    script_text: str

    def matches_distro(self, distro: str) -> bool:
        return distro in self.distros

    def matches_category(self, category: str) -> bool:
        return category in self.categories


class ManifestCatalog:
    def __init__(self, kind: CATALOG_KIND, config: ChrootConfig | None = None) -> None:
        self.kind = kind
        self.config = config
        self._manifest_dir = files("chrootctl").joinpath(f"resources/{kind}s")
        self._script_dir = files("chrootctl").joinpath(f"resources/{kind}-scripts")

    def list_entries(
        self,
        distro: str | None = None,
        category: str | None = None,
    ) -> list[ManifestEntry]:
        entries = sorted(self._load_all(), key=lambda item: item.name)
        if distro is not None:
            entries = [entry for entry in entries if entry.matches_distro(distro)]
        if category is not None:
            normalized_category = _normalize_category_name(category, filename="<filter>")
            entries = [entry for entry in entries if entry.matches_category(normalized_category)]
        return entries

    def get_entry(self, name: str) -> ManifestEntry:
        for entry in self._load_all():
            if entry.name == name:
                return entry
        raise KeyError(name)

    def categories(self, distro: str | None = None) -> list[str]:
        values: set[str] = set()
        for entry in self.list_entries(distro=distro):
            values.update(entry.categories)
        return sorted(values)

    def select_names(
        self,
        *,
        distro: str,
        prompt: str,
        category: str | None = None,
    ) -> list[str]:
        entries = self.list_entries(distro=distro, category=category)
        if not entries:
            return []
        choices = [
            Choice(
                value=entry.name,
                label=f"{entry.name} [{','.join(entry.categories) or 'uncategorized'}]",
                description=entry.description,
            )
            for entry in sorted(entries, key=lambda entry: ((entry.categories[0] if entry.categories else "uncategorized"), entry.name))
        ]
        return select_many(choices, prompt=prompt, multi=True)

    def apply(
        self,
        *,
        name: str,
        config: ChrootConfig,
        runner: SystemRunner,
        registry: ChrootRegistry,
        logger,
    ) -> CatalogApplyResult:
        record = registry.get(config.distro_name)
        if record is None or not bool(record.get("installed")):
            raise RuntimeError("chroot must be installed first")
        entry = self.get_entry(name)
        target_distro = str(record.get("distro", ""))
        if not entry.matches_distro(target_distro):
            raise RuntimeError(
                f"{self.kind} '{name}' does not support distro '{target_distro}'"
            )

        if self.kind == "tool" and entry.name == "sync-uid":
            UserSyncManager(config, runner, logger).sync_id(username=config.username, fix_ownership=True)
        else:
            self._run_script(entry, config=config, runner=runner, target_distro=target_distro)

        metadata = dict(record.get("metadata", {}))
        key = f"{self.kind}s"
        existing = _metadata_list(metadata.get(key))
        if name not in existing:
            existing.append(name)
        metadata[key] = ",".join(existing)
        registry.upsert(
            name=str(record["name"]),
            distro=str(record["distro"]),
            path=str(record["path"]),
            phase=str(record["phase"]),
            installed=bool(record["installed"]),
            arch=str(record["arch"]) if record.get("arch") is not None else None,
            release_name=str(record["release_name"]) if record.get("release_name") is not None else None,
            version=str(record["version"]) if record.get("version") is not None else None,
            metadata=metadata,
        )
        logger.info("applied %s %s to %s", self.kind, name, config.distro_name)
        return CatalogApplyResult(
            kind=self.kind,
            name=name,
            distro=target_distro,
            categories=entry.categories,
            applied=True,
        )

    def _run_script(
        self,
        entry: ManifestEntry,
        *,
        config: ChrootConfig,
        runner: SystemRunner,
        target_distro: str,
    ) -> None:
        env = {
            "CHROOTCTL_NAME": config.distro_name,
            "CHROOTCTL_DISTRO": target_distro,
            "CHROOTCTL_USERNAME": config.username,
        }
        if entry.script.endswith(".sh"):
            payload = "\n".join(["set -e", entry.script_text])
            runner.run(
                ["busybox", "chroot", str(config.chroot_base), "/bin/bash", "-lc", payload],
                chroot_env=True,
                env=env,
                capture_output=False,
            )
            return
        if entry.script.endswith(".py"):
            python_check = runner.run(
                ["busybox", "chroot", str(config.chroot_base), "python3", "--version"],
                check=False,
                chroot_env=True,
                env=env,
            )
            if python_check.returncode != 0:
                raise RuntimeError(f"{self.kind} '{entry.name}' requires python3 inside the chroot")
            runner.run(
                ["busybox", "chroot", str(config.chroot_base), "python3", "-"],
                chroot_env=True,
                env=env,
                capture_output=False,
                input_text=entry.script_text,
            )
            return
        raise RuntimeError(f"unsupported script type for {entry.script}")

    def _load_all(self) -> list[ManifestEntry]:
        entries_by_name: dict[str, ManifestEntry] = {}
        for path in sorted(self._manifest_dir.iterdir(), key=lambda item: item.name):
            if path.name.endswith(".yaml"):
                entry = self._load_manifest_text(
                    filename=path.name,
                    manifest_text=path.read_text(encoding="utf-8"),
                    script_text=self._load_builtin_script_text,
                    external=False,
                )
                entries_by_name[entry.name] = entry

        for manifest_dir in self._external_manifest_dirs:
            if not manifest_dir.exists():
                continue
            if not manifest_dir.is_dir():
                raise ValueError(f"{self.kind} manifest directory is not a directory: {manifest_dir}")
            for path in sorted(manifest_dir.iterdir(), key=lambda item: item.name):
                if path.suffix not in {".yaml", ".yml"}:
                    continue
                _validate_external_file(path, label=f"{self.kind} manifest")
                entry = self._load_manifest_text(
                    filename=str(path),
                    manifest_text=path.read_text(encoding="utf-8"),
                    script_text=self._load_external_script_text,
                    external=True,
                )
                if entry.name in entries_by_name:
                    raise ValueError(
                        f"external {self.kind} manifest {path} attempts to override existing catalog entry '{entry.name}'"
                    )
                entries_by_name[entry.name] = entry

        return list(entries_by_name.values())

    def _load_manifest_text(self, *, filename: str, manifest_text: str, script_text, external: bool = False) -> ManifestEntry:
        raw = yaml.safe_load(manifest_text)
        if not isinstance(raw, dict):
            raise ValueError(f"manifest {filename} must be a mapping")
        name = _validate_name(raw.get("name"), field="name", filename=filename)
        description = str(raw.get("description", "")).strip()
        if not description:
            raise ValueError(f"manifest {filename} missing description")
        script = _validate_script_name(raw.get("script"), filename=filename)
        distros = tuple(sorted(_normalize_manifest_distros(raw.get("distro"), filename=filename)))
        categories = tuple(sorted(_normalize_manifest_categories(raw.get("categories"), filename=filename)))
        resolved_script_text = script_text(script, filename=filename)
        if external:
            expected_sha256 = str(raw.get("sha256") or "").strip().lower()
            if len(expected_sha256) != 64 or any(char not in "0123456789abcdef" for char in expected_sha256):
                raise ValueError(f"external manifest {filename} must declare a lowercase sha256 for its script")
            actual_sha256 = hashlib.sha256(resolved_script_text.encode("utf-8")).hexdigest()
            if actual_sha256 != expected_sha256:
                raise ValueError(f"external manifest {filename} script sha256 mismatch")
        return ManifestEntry(
            kind=self.kind,
            name=name,
            description=description,
            distros=distros,
            categories=categories,
            script=script,
            script_text=resolved_script_text,
        )

    @property
    def _external_manifest_dirs(self) -> tuple[Path, ...]:
        if self.config is None:
            return ()
        return tuple(getattr(self.config, f"{self.kind}_manifest_dirs"))

    @property
    def _external_script_dirs(self) -> tuple[Path, ...]:
        if self.config is None:
            return ()
        return tuple(getattr(self.config, f"{self.kind}_script_dirs"))

    def _load_builtin_script_text(self, script: str, *, filename: str) -> str:
        path = self._script_dir.joinpath(script)
        if not path.is_file():
            raise ValueError(f"manifest {filename} references missing script: {script}")
        return path.read_text(encoding="utf-8")

    def _load_external_script_text(self, script: str, *, filename: str) -> str:
        for script_dir in self._external_script_dirs:
            if not script_dir.exists():
                continue
            if not script_dir.is_dir():
                raise ValueError(f"{self.kind} script directory is not a directory: {script_dir}")
            candidate = script_dir / script
            if candidate.exists() or candidate.is_symlink():
                _validate_external_file(candidate, label=f"{self.kind} script")
                return candidate.read_text(encoding="utf-8")
        raise ValueError(f"manifest {filename} references missing external script: {script}")


def _validate_name(value: object, *, field: str, filename: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest {filename} missing {field}")
    name = value.strip()
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if any(ch not in allowed for ch in name):
        raise ValueError(f"manifest {filename} has invalid {field}: {name}")
    return name


def _validate_external_file(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a regular file: {path}")
    info = path.stat()
    allowed_owners = {os.geteuid(), 0}
    if info.st_uid not in allowed_owners:
        raise ValueError(f"{label} has untrusted owner uid {info.st_uid}: {path}")
    if info.st_mode & 0o022:
        raise ValueError(f"{label} must not be group/world writable: {path}")


def _validate_script_name(value: object, *, filename: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest {filename} missing script")
    script = value.strip()
    if "/" in script or ".." in script or "\\" in script:
        raise ValueError(f"manifest {filename} has invalid script path: {script}")
    if Path(script).suffix not in SUPPORTED_SCRIPT_SUFFIXES:
        raise ValueError(
            f"manifest {filename} has unsupported script suffix: {Path(script).suffix or '<none>'}"
        )
    return script


def _normalize_manifest_distros(raw: object, *, filename: str) -> set[str]:
    if raw == "all":
        return set(SUPPORTED_DISTROS)
    if isinstance(raw, str):
        values = {raw}
    elif isinstance(raw, list) and raw and all(isinstance(item, str) for item in raw):
        values = set(raw)
    else:
        raise ValueError(
            f"manifest {filename} distro must be a string, a non-empty list of strings, or 'all'"
        )
    unknown = values - SUPPORTED_DISTROS
    if unknown:
        raise ValueError(
            f"manifest {filename} has unsupported distro values: {', '.join(sorted(unknown))}"
        )
    return values


def _normalize_manifest_categories(raw: object, *, filename: str) -> set[str]:
    if raw is None:
        return set()
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"manifest {filename} categories must be a non-empty list of strings")
    normalized: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"manifest {filename} categories must be a non-empty list of strings")
        normalized.add(_normalize_category_name(item, filename=filename))
    return normalized


def _normalize_category_name(value: str, *, filename: str) -> str:
    category = value.strip().lower().replace("_", "-").replace(" ", "-")
    if not category:
        raise ValueError(f"manifest {filename} has invalid category: {value!r}")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(ch not in allowed for ch in category):
        raise ValueError(f"manifest {filename} has invalid category: {value!r}")
    return category


def _metadata_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.split(",") if item]
    return []


def _grouped_selection_lines(entries: list[ManifestEntry]) -> list[str]:
    def sort_key(entry: ManifestEntry) -> tuple[str, str]:
        primary = entry.categories[0] if entry.categories else "uncategorized"
        return (primary, entry.name)

    lines: list[str] = []
    for entry in sorted(entries, key=sort_key):
        category_label = ",".join(entry.categories) or "uncategorized"
        lines.append(f"{entry.name}\t{category_label}\t{entry.description}")
    return lines
