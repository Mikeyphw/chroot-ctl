from __future__ import annotations

import json
import tarfile
import tempfile
from pathlib import Path

from ..models import SupportBundleResult
from .context import ServiceContainer


class SupportService:
    def __init__(self, services: ServiceContainer) -> None:
        self.services = services

    def export_bundle(self, archive: Path | None = None, *, jobs=None) -> SupportBundleResult:
        base_dir = self.services.base_config.database_path.parent
        target = (archive or (Path.cwd() / "chrootctl-support-bundle.tar.gz")).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="chrootctl-support-") as tmp:
            tmpdir = Path(tmp)
            manifest = {
                "config_path": str(self.services.base_config.config_path()),
                "database_path": str(self.services.base_config.database_path),
                "log_file": str(self.services.base_config.log_file),
                "job_count": len(jobs.list_recent(limit=20)) if jobs is not None else 0,
            }
            (tmpdir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

            events = [event.to_display_dict() for event in self.services.audit().recent(limit=100)]
            (tmpdir / "events.json").write_text(json.dumps(events, indent=2, sort_keys=True), encoding="utf-8")

            doctor = self.services.system().host_doctor()
            if isinstance(doctor, dict):
                checks = doctor.get("checks", [])
                advisories = doctor.get("advisories", [])
            else:
                checks = doctor
                advisories = []
            (tmpdir / "doctor-host.json").write_text(
                json.dumps({"checks": [row.to_display_dict() for row in checks], "advisories": advisories}, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            registry_rows = [row.to_display_dict() for row in self.services.chroots().list()]
            (tmpdir / "chroots.json").write_text(json.dumps(registry_rows, indent=2, sort_keys=True), encoding="utf-8")

            config_payload = {
                "chroot_root": str(self.services.base_config.chroot_root),
                "distro_name": self.services.base_config.distro_name,
                "username": self.services.base_config.username,
                "target_arch": self.services.base_config.target_arch,
                "termux_home": str(self.services.base_config.termux_home),
                "termux_prefix": str(self.services.base_config.termux_prefix),
                "log_file": "<redacted>",
                "database_path": "<redacted>",
            }
            (tmpdir / "config-sanitized.json").write_text(json.dumps(config_payload, indent=2, sort_keys=True), encoding="utf-8")

            if jobs is not None:
                job_rows = []
                for job in jobs.list_recent(limit=25):
                    payload = job.to_event_payload(log_download_url=f"/jobs/{job.job_id}/logs/download")
                    payload["log_lines"] = list(job.log_lines)
                    job_rows.append(payload)
                (tmpdir / "jobs.json").write_text(json.dumps(job_rows, indent=2, sort_keys=True), encoding="utf-8")

            log_path = self.services.base_config.log_file.expanduser()
            if log_path.exists():
                (tmpdir / "logs").mkdir(parents=True, exist_ok=True)
                try:
                    text = log_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    text = ""
                (tmpdir / "logs" / "chrootctl.log").write_text(text, encoding="utf-8")

            with tarfile.open(target, "w:gz") as tf:
                for child in tmpdir.iterdir():
                    tf.add(child, arcname=child.name)

        self.services.audit().record("support-bundle.export", target=str(target), message="Support bundle exported")
        return SupportBundleResult(archive=target, included=("manifest.json", "events.json", "doctor-host.json", "chroots.json", "config-sanitized.json", "jobs.json", "logs/chrootctl.log"))
