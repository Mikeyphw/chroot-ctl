from __future__ import annotations

from pathlib import Path

from ..models import RegistryRepairResult
from ..validation import validate_chroot_name
from .context import ServiceContainer


class RepairService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def preview_items(self) -> list[dict[str, str | list[str]]]:
        registry_rows = {str(row.get("name", "")): row for row in self.services.registry.list()}
        items: list[dict[str, str | list[str]]] = []
        seen: set[str] = set()
        for directory in self._candidate_dirs():
            name = directory.name
            record = registry_rows.get(name)
            item_id = f"chroot:{name}"
            seen.add(name)
            if record is None:
                items.append(
                    {
                        "item_id": item_id,
                        "name": name,
                        "kind": "missing-record",
                        "severity": "warn",
                        "action": "register",
                        "path": str(directory),
                        "expected_path": "",
                        "summary": f"Filesystem path exists without a registry record: {directory}",
                        "impact": "Registers the existing directory so it shows up in the dashboard and Web UI again.",
                        "current_state": "No registry record exists for this directory.",
                        "proposed_state": f"Create a recovered registry record pointing to {directory}.",
                        "diff_lines": [
                            f"- registry[{name}] = missing",
                            f"+ registry[{name}].path = {directory}",
                            "+ registry[<name>].phase = registered",
                            "+ registry[<name>].metadata.recovered = yes",
                        ],
                    }
                )
                continue
            record_path = Path(str(record.get("path", ""))).expanduser()
            if record_path != directory:
                items.append(
                    {
                        "item_id": item_id,
                        "name": name,
                        "kind": "mismatched-path",
                        "severity": "warn",
                        "action": "fix-path",
                        "path": str(directory),
                        "expected_path": str(record_path),
                        "summary": f"Registry path does not match filesystem path for {name}",
                        "impact": "Updates the registry path so start, shell, doctor, and transfer actions point at the real directory.",
                        "current_state": f"Registry points to {record_path}.",
                        "proposed_state": f"Registry will point to {directory}.",
                        "diff_lines": [
                            f"- registry[{name}].path = {record_path}",
                            f"+ registry[{name}].path = {directory}",
                        ],
                    }
                )
        for name, record in registry_rows.items():
            if name in seen:
                continue
            record_path = Path(str(record.get("path", ""))).expanduser()
            if not record_path.exists():
                items.append(
                    {
                        "item_id": f"registry:{name}",
                        "name": name,
                        "kind": "missing-path",
                        "severity": "bad",
                        "action": "remove-record",
                        "path": str(record_path),
                        "expected_path": str(record_path),
                        "summary": f"Registry record points to a missing path: {record_path}",
                        "impact": "Removes a broken registry entry so the UI stops offering actions that cannot work.",
                        "current_state": f"Registry points to a missing path: {record_path}.",
                        "proposed_state": f"Delete the registry record for {name}.",
                        "diff_lines": [
                            f"- registry[{name}] = {record_path}",
                            "+ registry[<name>] removed",
                        ],
                    }
                )
        return items

    def preview_plan(self, decisions: list[dict[str, str]]) -> dict[str, object]:
        preview_items = {str(item["item_id"]): item for item in self.preview_items()}
        selected: list[dict[str, object]] = []
        summary = {
            "selected_count": 0,
            "register_count": 0,
            "fix_path_count": 0,
            "remove_record_count": 0,
            "skip_count": 0,
            "warnings": [],
            "next_steps": [],
        }
        for decision in decisions:
            item_id = str(decision.get("item_id", "")).strip()
            item = preview_items.get(item_id)
            if item is None:
                raise RuntimeError(f"repair decision is stale or unknown: {item_id}")
            action = str(decision.get("action", "")).strip()
            allowed_action = {
                "missing-record": "register",
                "mismatched-path": "fix-path",
                "missing-path": "remove-record",
            }.get(str(item.get("kind", "")))
            if action == "skip":
                summary["skip_count"] += 1
                continue
            if allowed_action is None or action != allowed_action:
                raise RuntimeError(f"repair action {action!r} is not valid for {item.get('kind')!r}")
            summary["selected_count"] += 1
            if action == "register":
                summary["register_count"] += 1
            elif action == "fix-path":
                summary["fix_path_count"] += 1
            elif action == "remove-record":
                summary["remove_record_count"] += 1
            selected.append(
                {
                    "item_id": item_id,
                    "name": item["name"],
                    "kind": item["kind"],
                    "severity": item.get("severity", "warn"),
                    "action": action,
                    "summary": item["summary"],
                    "impact": item.get("impact", ""),
                    "path": item.get("path", ""),
                    "expected_path": item.get("expected_path", ""),
                }
            )
        warnings: list[str] = []
        if summary["remove_record_count"]:
            warnings.append("Removing registry records is destructive for UI metadata, but does not delete filesystem data.")
        if summary["register_count"]:
            warnings.append("Recovered chroots may need distro/release metadata review after registration.")
        if summary["fix_path_count"]:
            warnings.append("Re-run doctor or status after fixing paths to confirm runtime wiring.")
        next_steps = ["Queue the repair job and review the result on the Jobs page."] if summary["selected_count"] else ["Select at least one repair action to continue."]
        summary["warnings"] = warnings
        summary["next_steps"] = next_steps
        return {"summary": summary, "selected": selected, "ok": bool(summary["selected_count"])}

    def apply_registry_repair_plan(self, decisions: list[dict[str, str]]) -> RegistryRepairResult:
        repaired_records: list[str] = []
        removed_records: list[str] = []
        missing_records: list[str] = []
        missing_paths: list[str] = []
        mismatched_paths: list[str] = []
        mutations: list[dict[str, object]] = []
        preview_items = {str(item["item_id"]): item for item in self.preview_items()}

        # Preflight the full plan before the first database write so a stale/invalid
        # candidate cannot leave a partially applied repair set.
        for decision in decisions:
            item_id = str(decision.get("item_id", "")).strip()
            item = preview_items.get(item_id)
            if item is None:
                raise RuntimeError(f"repair decision is stale or unknown: {item_id}")
            action = str(decision.get("action", "")).strip() or str(item.get("action", ""))
            if action == "skip":
                continue
            name = str(item["name"])
            kind = str(item["kind"])
            allowed_action = {
                "missing-record": "register",
                "mismatched-path": "fix-path",
                "missing-path": "remove-record",
            }.get(kind)
            if allowed_action is None or action != allowed_action:
                raise RuntimeError(f"repair action {action!r} is not valid for {kind!r}")

            if kind == "missing-record":
                missing_records.append(name)
                directory = self._validated_candidate(name, Path(str(item["path"])))
                mutations.append(
                    {
                        "action": "upsert",
                        "name": name,
                        "distro": "unknown",
                        "path": str(directory),
                        "phase": "registered",
                        "installed": False,
                        "arch": "",
                        "release_name": "",
                        "version": "",
                        "metadata": {"recovered": "yes", "repair_source": "filesystem-scan"},
                    }
                )
                repaired_records.append(name)
            elif kind == "mismatched-path":
                mismatched_paths.append(name)
                directory = self._validated_candidate(name, Path(str(item["path"])))
                record = self.services.registry.get(name)
                if record is None:
                    raise RuntimeError(f"registry record disappeared after preview: {name}")
                mutations.append(
                    {
                        "action": "upsert",
                        "name": name,
                        "distro": str(record.get("distro", "unknown")),
                        "path": str(directory),
                        "phase": str(record.get("phase", "registered")),
                        "installed": bool(record.get("installed")),
                        "arch": str(record.get("arch", "")),
                        "release_name": str(record.get("release_name", "")),
                        "version": str(record.get("version", "")),
                        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
                    }
                )
                repaired_records.append(name)
            elif kind == "missing-path":
                missing_paths.append(name)
                record = self.services.registry.get(name)
                if record is None:
                    raise RuntimeError(f"registry record disappeared after preview: {name}")
                record_path = Path(str(record.get("path", ""))).expanduser()
                if record_path.exists():
                    raise RuntimeError(f"repair decision is stale because the missing path now exists: {record_path}")
                mutations.append({"action": "delete", "name": name})
                removed_records.append(name)

        self.services.registry.apply_chroot_mutations(mutations)
        result = RegistryRepairResult(
            scanned_paths=len(self._candidate_dirs()),
            missing_records=tuple(missing_records),
            missing_paths=tuple(missing_paths),
            mismatched_paths=tuple(mismatched_paths),
            repaired_records=tuple(repaired_records),
            removed_records=tuple(removed_records),
            preview=False,
            next_steps=("Review repaired chroots on the dashboard.",),
        )
        self.services.audit().record(
            "registry.repair.apply",
            target="registry",
            message="Applied selective registry repair",
            metadata={"repaired": ",".join(repaired_records), "removed": ",".join(removed_records)},
        )
        return result

    def _candidate_dirs(self) -> list[Path]:
        root = self.services.base_config.chroot_root
        if not root.exists():
            return []
        items: list[Path] = []
        resolved_root = root.resolve()
        for child in sorted(root.iterdir()):
            name = child.name
            if child.is_symlink() or not child.is_dir():
                continue
            if name.startswith(".") or name in {"tmp", "cache", "logs"}:
                continue
            try:
                validate_chroot_name(name, field="repair candidate")
                resolved = child.resolve(strict=True)
                resolved.relative_to(resolved_root)
            except (OSError, ValueError):
                continue
            if resolved != child.absolute():
                continue
            items.append(child)
        return items

    def _validated_candidate(self, name: str, directory: Path) -> Path:
        validate_chroot_name(name, field="repair candidate")
        root = self.services.base_config.chroot_root.resolve()
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(f"repair candidate is no longer a regular directory: {directory}")
        resolved = directory.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"repair candidate escaped the configured chroot root: {directory}") from exc
        if resolved.name != name:
            raise RuntimeError(f"repair candidate name changed after preview: {name}")
        return resolved

    def preview_registry_repair(self) -> RegistryRepairResult:
        return self._repair(preview=True)

    def apply_registry_repair(self) -> RegistryRepairResult:
        return self._repair(preview=False)

    def _repair(self, *, preview: bool) -> RegistryRepairResult:
        registry_rows = {str(row.get("name", "")): row for row in self.services.registry.list()}
        candidate_dirs = self._candidate_dirs()
        candidate_names = {item.name for item in candidate_dirs}

        missing_records: list[str] = []
        missing_paths: list[str] = []
        mismatched_paths: list[str] = []
        repaired_records: list[str] = []
        removed_records: list[str] = []

        for directory in candidate_dirs:
            name = directory.name
            record = registry_rows.get(name)
            if record is None:
                missing_records.append(name)
                if not preview:
                    metadata = {"recovered": "yes", "repair_source": "filesystem-scan"}
                    self.services.registry.upsert(
                        name=name,
                        distro=str(metadata.get("distro", "unknown")),
                        path=str(directory),
                        phase="registered",
                        installed=False,
                        arch="",
                        release_name="",
                        version="",
                        metadata=metadata,
                    )
                    repaired_records.append(name)
            else:
                record_path = Path(str(record.get("path", ""))).expanduser()
                if record_path != directory:
                    mismatched_paths.append(name)
                    if not preview:
                        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
                        self.services.registry.upsert(
                            name=name,
                            distro=str(record.get("distro", "unknown")),
                            path=str(directory),
                            phase=str(record.get("phase", "registered")),
                            installed=bool(record.get("installed")),
                            arch=str(record.get("arch", "")),
                            release_name=str(record.get("release_name", "")),
                            version=str(record.get("version", "")),
                            metadata=metadata,
                        )
                        repaired_records.append(name)

        for name, record in registry_rows.items():
            record_path = Path(str(record.get("path", ""))).expanduser()
            if name not in candidate_names and not record_path.exists():
                missing_paths.append(name)
                if not preview:
                    self.services.registry.delete(name)
                    removed_records.append(name)

        next_steps = []
        if missing_records:
            next_steps.append("Review recovered chroots and update distro/release metadata if needed.")
        if missing_paths:
            next_steps.append("Re-import missing chroots or restore from snapshot/export if they were removed accidentally.")
        if mismatched_paths:
            next_steps.append("Re-run doctor/status for repaired chroots to confirm runtime paths are correct.")
        if not next_steps:
            next_steps.append("Registry and filesystem look consistent.")

        result = RegistryRepairResult(
            scanned_paths=len(candidate_dirs),
            missing_records=tuple(missing_records),
            missing_paths=tuple(missing_paths),
            mismatched_paths=tuple(mismatched_paths),
            repaired_records=tuple(repaired_records),
            removed_records=tuple(removed_records),
            preview=preview,
            next_steps=tuple(next_steps),
        )
        self.services.audit().record(
            "registry.repair.preview" if preview else "registry.repair.apply",
            target="registry",
            message="Previewed registry repair" if preview else "Applied registry repair",
            metadata={
                "missing_records": str(len(missing_records)),
                "missing_paths": str(len(missing_paths)),
                "mismatched_paths": str(len(mismatched_paths)),
                "repaired_records": str(len(repaired_records)),
                "removed_records": str(len(removed_records)),
            },
        )
        return result
