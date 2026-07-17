
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

from .jobs import JOB_FAILED, JOB_QUEUED, JOB_RUNNING, JOB_SUCCEEDED, _JobRecord
from ..models import AuditEvent, CheckRow, ChrootDetails, DashboardSummary, LogSnapshot, SnapshotRecord


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    name: str
    kind: str
    description: str
    categories: list[str] = field(default_factory=list)
    distros: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


FIXTURE_MODE = os.environ.get("CHROOTCTL_E2E_DASHBOARD_MODE", "dense").strip().lower() or "dense"


class _E2ERepairService:
    def preview_plan(self, decisions):
        selected = [item for item in decisions if item.get("selected", True)]
        register = sum(1 for item in selected if item.get("action") == "register")
        fix = sum(1 for item in selected if item.get("action") == "fix-path")
        remove = sum(1 for item in selected if item.get("action") == "remove-record")
        return {
            "selected_count": len(selected),
            "register_count": register,
            "fix_count": fix,
            "remove_count": remove,
            "warnings": [
                "Fixture mode previews seeded actions only.",
                "Review before queueing a real repair outside fixture mode.",
            ],
            "queued_actions": [item.get("action", "noop") for item in selected],
            "current_state_summary": "Seeded registry drift exists across ubuntu, devbox, and rescue.",
            "planned_state_summary": "Selected registry records will be registered, fixed, or removed.",
            "next_steps": ["Queue the repair job after preview.", "Open the jobs page to watch the result."],
        }

    def preview_items(self):
        return [
            {
                "item_id": "missing-reg-ubuntu",
                "name": "ubuntu",
                "kind": "missing-record",
                "severity": "warn",
                "summary": "Filesystem chroot exists without a registry record.",
                "path": "/data/local/tmp/ubuntu",
                "expected_path": "—",
                "action": "register",
                "current_state": "Directory exists on disk but registry does not know about it.",
                "proposed_state": "Registry record will be created for the discovered directory.",
                "impact": "The chroot becomes manageable again from the UI and CLI.",
                "diff_lines": [
                    "- registry: missing",
                    "+ registry.name = ubuntu",
                    "+ registry.path = /data/local/tmp/ubuntu",
                ],
            },
            {
                "item_id": "mismatch-devbox",
                "name": "devbox",
                "kind": "mismatched-path",
                "severity": "bad",
                "summary": "Registry points at an outdated path.",
                "path": "/data/local/tmp/devbox",
                "expected_path": "/legacy/devbox",
                "action": "fix-path",
                "current_state": "Registry path is stale and no longer matches the on-disk chroot.",
                "proposed_state": "Registry path will be updated to the discovered current path.",
                "impact": "Open shell, status, and maintenance actions will target the correct directory.",
                "diff_lines": [
                    "- registry.path = /legacy/devbox",
                    "+ registry.path = /data/local/tmp/devbox",
                ],
            },
            {
                "item_id": "missing-path-rescue",
                "name": "rescue",
                "kind": "missing-path",
                "severity": "warn",
                "summary": "Registry record points at a missing chroot directory.",
                "path": "—",
                "expected_path": "/data/local/tmp/rescue",
                "action": "remove-record",
                "current_state": "Registry contains a stale entry but the chroot rootfs is gone.",
                "proposed_state": "Broken registry entry will be removed.",
                "impact": "Dashboard and chroot lists stop pointing at a missing target.",
                "diff_lines": [
                    "- registry.name = rescue",
                    "- registry.path = /data/local/tmp/rescue",
                ],
            },
        ]

    def preview_registry_repair(self):
        return {
            "scanned_paths": 4,
            "missing_records": ["ubuntu"],
            "missing_paths": ["rescue"],
            "mismatched_paths": [{"name": "devbox", "record_path": "/legacy/devbox", "actual_path": "/data/local/tmp/devbox"}],
        }


def _seeded_snapshots() -> list[SnapshotRecord]:
    return [
        SnapshotRecord(
            snapshot_id=1,
            name="snap-good-001",
            chroot_name="androidos",
            created_at="2026-06-24T12:00:00Z",
            path="/data/local/tmp/androidos/.snapshots/snap-good-001",
            kind="filesystem-copy",
            note="Known good before risky changes",
            size_bytes=1048576,
        ),
        SnapshotRecord(
            snapshot_id=2,
            name="snap-devbox-2026-06-24",
            chroot_name="devbox",
            created_at="2026-06-24T08:30:00Z",
            path="/data/local/tmp/devbox/.snapshots/snap-devbox-2026-06-24",
            kind="filesystem-copy",
            note="Pre-upgrade safety snapshot",
            size_bytes=2097152,
        ),
        SnapshotRecord(
            snapshot_id=3,
            name="snap-rescue-empty",
            chroot_name="rescue",
            created_at="2026-06-23T06:00:00Z",
            path="/data/local/tmp/rescue/.snapshots/snap-rescue-empty",
            kind="filesystem-copy",
            note="Stale snapshot retained for repair previews",
            size_bytes=0,
        ),
    ]


class _E2ESnapshotService:
    def list(self, *, chroot_name: str | None = None, limit: int = 20):
        items = _seeded_snapshots()
        filtered = [item for item in items if chroot_name is None or item.chroot_name == chroot_name]
        return filtered[:limit]


def _seeded_chroots() -> list[ChrootDetails]:
    dense = [
        ChrootDetails(
            name="androidos",
            distro="ubuntu",
            path="/data/local/tmp/androidos",
            release_name="noble",
            version="24.04",
            phase="ready",
            installed=True,
            arch="arm64",
            created_at="2026-06-24T10:00:00Z",
            updated_at="2026-06-24T12:00:00Z",
            configured_mounts="/sdcard,/tmp",
            extra_packages="curl git sudo",
            locale="en_US.UTF-8",
            metadata={"fixture": "true", "role": "daily-driver"},
        ),
        ChrootDetails(
            name="devbox",
            distro="ubuntu",
            path="/data/local/tmp/devbox",
            release_name="noble",
            version="24.04",
            phase="ready",
            installed=True,
            arch="arm64",
            created_at="2026-06-22T10:00:00Z",
            updated_at="2026-06-24T11:00:00Z",
            configured_mounts="/sdcard,/tmp,/src",
            extra_packages="build-essential git python3",
            locale="en_US.UTF-8",
            metadata={"fixture": "true", "role": "development"},
        ),
        ChrootDetails(
            name="rescue",
            distro="ubuntu",
            path="/data/local/tmp/rescue",
            release_name="noble",
            version="24.04",
            phase="bootstrap",
            installed=False,
            arch="arm64",
            created_at="2026-06-21T08:00:00Z",
            updated_at="2026-06-21T08:30:00Z",
            configured_mounts="",
            extra_packages="",
            locale="C.UTF-8",
            metadata={"fixture": "true", "role": "recovery"},
        ),
        ChrootDetails(
            name="fedora-dev",
            distro="fedora",
            path="/data/local/tmp/fedora-dev",
            release_name="40",
            version="40",
            phase="ready",
            installed=True,
            arch="arm64",
            created_at="2026-06-20T08:00:00Z",
            updated_at="2026-06-24T09:00:00Z",
            configured_mounts="/sdcard,/workspace",
            extra_packages="dnf-plugins-core git",
            locale="en_US.UTF-8",
            metadata={"fixture": "true", "role": "foreign-arch-demo"},
        ),
    ]
    if FIXTURE_MODE == "single":
        return dense[:1]
    return dense


class _E2EChrootService:
    def list(self):
        return _seeded_chroots()

    def get(self, name: str):
        for item in self.list():
            if item.name == name:
                return item
        raise KeyError(name)

    def package_diff(self, left: str, right: str):
        return {"left": left, "right": right, "added": ["curl", "git"], "removed": ["nano"], "changed": ["python3"]}


class _E2ESystemService:
    def status(self, name: str):
        rows = {
            "androidos": [
                CheckRow(check="mounts", result="PASS", detail="androidos runtime mounts look healthy", next="Open shell safely."),
                CheckRow(check="shell", result="PASS", detail="androidos shell entrypoint is available", next="Use start or exec actions."),
            ],
            "devbox": [
                CheckRow(check="mounts", result="PASS", detail="devbox runtime mounts look healthy", next="Ready for build tasks."),
                CheckRow(check="shell", result="WARN", detail="Interactive shell can start but tmux integration is not configured.", next="Use standard shell entry."),
            ],
            "rescue": [
                CheckRow(check="mounts", result="FAIL", detail="rescue rootfs is missing one runtime bind mount.", next="Run repair or restore a snapshot."),
                CheckRow(check="shell", result="FAIL", detail="rescue shell entrypoint is not available yet.", next="Complete install or restore."),
            ],
            "fedora-dev": [
                CheckRow(check="mounts", result="PASS", detail="fedora-dev runtime mounts look healthy", next="Foreign-arch helpers are available."),
                CheckRow(check="shell", result="PASS", detail="fedora-dev shell entrypoint is available", next="Open shell."),
            ],
        }
        return rows.get(name, rows["androidos"])

    def doctor(self, name: str):
        rows = {
            "androidos": [
                CheckRow(check="filesystem", result="PASS", detail="androidos rootfs looks valid", next="Create a snapshot before risky changes."),
                CheckRow(check="network", result="WARN", detail="Fixture mode skips real network probing", next="Run host doctor outside fixture mode for real checks."),
            ],
            "devbox": [
                CheckRow(check="filesystem", result="PASS", detail="devbox rootfs looks valid", next="Ready for upgrades."),
                CheckRow(check="packages", result="WARN", detail="Package cache is larger than usual.", next="Consider export or cleanup."),
            ],
            "rescue": [
                CheckRow(check="filesystem", result="FAIL", detail="rescue rootfs is incomplete.", next="Restore latest snapshot or remove stale record."),
                CheckRow(check="users", result="WARN", detail="No confirmed non-root Linux user yet.", next="Retry install with fixes."),
            ],
            "fedora-dev": [
                CheckRow(check="filesystem", result="PASS", detail="fedora-dev rootfs looks valid", next="Proceed with maintenance."),
                CheckRow(check="qemu", result="WARN", detail="Foreign-arch finalize would require emulation on a different host.", next="Use extract-only guidance if needed."),
            ],
        }
        return rows.get(name, rows["androidos"])

    def dashboard(self):
        log_file = Path(tempfile.gettempdir()) / "chrootctl-e2e-dashboard.log"
        log_file.write_text(
            "INFO dashboard: seeded fixture dashboard ready\n"
            "WARN doctor: rescue requires recovery\n"
            "INFO jobs: multiple mixed job states active\n",
            encoding="utf-8",
        )
        return DashboardSummary(
            target_name="androidos",
            chroots=tuple(),
            status_checks=tuple(self.status("androidos")),
            doctor_checks=tuple(self.doctor("androidos")),
            logs=LogSnapshot(log_file=log_file, level=None, lines=tuple(log_file.read_text(encoding="utf-8").splitlines())),
        )

    def host_doctor(self):
        return [
            CheckRow(check="python", result="PASS", detail="Fixture runtime dependencies loaded.", next="Ready for UI flows."),
            CheckRow(check="busybox", result="PASS", detail="busybox is available in fixture mode.", next="Core commands can be simulated."),
            CheckRow(check="network", result="WARN", detail="Network probing is stubbed in fixture mode.", next="Run real doctor outside fixture mode."),
        ]

    def foreign_arch_advisories(self):
        return [
            {
                "target_arch": "amd64",
                "mode": "extract-only",
                "title": "Foreign-arch install guidance",
                "message": "This seeded dashboard includes a foreign-arch target to exercise guidance cards.",
                "next_steps": ["Use transfer/export from another host.", "Finalize later on a compatible device."],
            }
        ]

    def cross_arch_state(self):
        return {
            "host_arch": "arm64",
            "targets": [
                {"arch": "arm64", "ready": True, "mode": "native"},
                {"arch": "amd64", "ready": False, "mode": "extract-only"},
            ],
        }

    def quickstart(self):
        return {
            "host_rows": self.host_doctor(),
            "blockers": [],
            "warnings": ["Fixture mode is enabled for browser tests.", "rescue needs recovery action."],
            "chroot_count": len(_seeded_chroots()),
            "recommended_name": "androidos",
            "defaults": {"distro": "ubuntu", "preset": "minimal-server", "release": "noble", "name": "androidos"},
            "target_user": "mike",
            "can_install": True,
            "shell_target": "androidos",
            "shell_command": "chrootctl start androidos",
            "install_command": "chrootctl install ubuntu --name androidos --preset minimal-server --release noble --username mike",
            "use_steps": [
                "Run readiness checks.",
                "Open the failed rescue job to exercise retry paths.",
                "Recover rescue from the latest snapshot if needed.",
            ],
        }


class _E2ECatalogKindService:
    def __init__(self, entries):
        self._entries = entries

    def list_entries(self, distro: str | None = None, category: str | None = None):
        entries = list(self._entries)
        if category:
            entries = [entry for entry in entries if category in getattr(entry, "categories", [])]
        if distro:
            entries = [entry for entry in entries if not getattr(entry, "distros", []) or distro in getattr(entry, "distros", [])]
        return entries

    def get_entry(self, entry_name: str):
        for entry in self._entries:
            if entry.name == entry_name:
                return entry
        raise KeyError(entry_name)

    def categories(self, distro: str | None = None):
        values = sorted({category for entry in self.list_entries(distro=distro) for category in getattr(entry, "categories", [])})
        return values


class _E2ECatalogService:
    def __init__(self):
        self._services = {
            "tool": _E2ECatalogKindService([
                CatalogEntry(name="git", kind="tool", description="Install git inside the chroot.", categories=["dev"], distros=["ubuntu"], steps=["apt install git"]),
                CatalogEntry(name="curl", kind="tool", description="Install curl for network fetches.", categories=["network"], distros=["ubuntu"], steps=["apt install curl"]),
                CatalogEntry(name="htop", kind="tool", description="Interactive process viewer.", categories=["ops"], distros=["ubuntu"], steps=["apt install htop"]),
            ]),
            "addon": _E2ECatalogKindService([
                CatalogEntry(name="xfce-tweaks", kind="addon", description="Apply lightweight desktop tweaks.", categories=["desktop"], distros=["ubuntu"], steps=["copy config"]),
                CatalogEntry(name="dev-shell", kind="addon", description="Developer shell aliases and prompt.", categories=["dev"], distros=["ubuntu"], steps=["copy profile"]),
            ]),
        }

    def __call__(self, kind: str):
        return self._services[kind]


class _E2EUsersService:
    def __init__(self, name: str):
        self._name = name

    def list(self):
        if self._name == "rescue":
            return []
        if self._name == "devbox":
            return [
                {"username": "mike", "uid": 10431, "groups": ["wheel", "storage"]},
                {"username": "builder", "uid": 10432, "groups": ["wheel"]},
            ]
        return [{"username": "mike", "uid": 10431, "groups": ["wheel", "storage"]}]

    def show(self, username: str):
        if username not in {"mike", "builder"}:
            raise KeyError(username)
        return {"username": username, "uid": 10431 if username == "mike" else 10432, "shell": "/bin/bash", "groups": ["wheel", "storage"], "sudo": True}

    def show_id(self, username: str):
        if username not in {"mike", "builder"}:
            raise KeyError(username)
        return {"uid": 10431 if username == "mike" else 10432, "gid": 10431 if username == "mike" else 10432, "groups": ["wheel", "storage"]}


class _E2EAuditService:
    def recent(self, limit: int = 8):
        return self.audit_events(limit=limit)

    def audit_events(self, limit: int = 20):
        return [
            AuditEvent(event_id=1, event_type="install", actor="fixture", target="androidos", result="failed", message="Install failed during finalize.", created_at="2026-06-24T12:00:00Z"),
            AuditEvent(event_id=2, event_type="snapshot", actor="fixture", target="androidos", result="succeeded", message="Snapshot created successfully.", created_at="2026-06-24T12:05:00Z"),
            AuditEvent(event_id=3, event_type="upgrade", actor="fixture", target="devbox", result="running", message="Upgrade in progress.", created_at="2026-06-24T12:07:00Z"),
            AuditEvent(event_id=4, event_type="repair", actor="fixture", target="rescue", result="queued", message="Repair queued from the dashboard.", created_at="2026-06-24T12:08:00Z"),
        ][:limit]


class _E2ESupportService:
    def audit_events(self, limit: int = 20):
        return [event.to_display_dict() for event in _E2EAuditService().audit_events(limit=limit)]


class E2EServiceWrapper:
    def __init__(self, base):
        self._base = base
        self._repair = _E2ERepairService()
        self._snapshots = _E2ESnapshotService()
        self._system = _E2ESystemService()
        self._chroots = _E2EChrootService()
        self._catalog = _E2ECatalogService()
        self._support = _E2ESupportService()
        self._audit = _E2EAuditService()

    def __getattr__(self, name):
        return getattr(self._base, name)

    def repair(self):
        return self._repair

    def snapshots(self):
        return self._snapshots

    def system(self):
        return self._system

    def chroots(self):
        return self._chroots

    def catalog(self, kind: str):
        return self._catalog(kind)

    def users(self, name: str):
        return _E2EUsersService(name)

    def support(self):
        return self._support

    def audit(self):
        return self._audit


def _seed_jobs(app) -> None:
    jobs = app.state.jobs
    temp_dir = Path(tempfile.gettempdir())
    log_path = temp_dir / "chrootctl-e2e-failed.log"
    log_path.write_text(
        "bootstrap: fetching ubuntu base\n"
        "finalize: no non-root users available\n"
        "hint: retry with username or repair enabled\n",
        encoding="utf-8",
    )
    running_log = temp_dir / "chrootctl-e2e-running.log"
    running_log.write_text(
        "upgrade: refreshing package indexes\n"
        "upgrade: installing updates\n",
        encoding="utf-8",
    )

    records = [
        _JobRecord(
            job_id="e2e-failed-install",
            kind="install",
            title="Fixture failed install",
            state=JOB_FAILED,
            progress_text="Failed during finalize",
            created_at=1.0,
            started_at=2.0,
            finished_at=3.0,
            target_name="androidos",
            log_path=log_path,
            error="Choose user: no non-root users available; pass --username",
            next_steps=("Open retry with fixes.", "Restore latest snapshot if the target is broken."),
            progress_detail={"phase": "finalize", "percent": 72},
            progress_events=(),
            retry={
                "action": "install.submit",
                "payload": {
                    "distro": "ubuntu",
                    "name": "androidos",
                    "username": "",
                    "preset": "minimal-server",
                    "release": "noble",
                    "mirror": "auto",
                    "repair": False,
                },
            },
        ),
        _JobRecord(
            job_id="e2e-build-success",
            kind="build",
            title="Fixture module build",
            state=JOB_SUCCEEDED,
            progress_text="Module artifact ready",
            created_at=4.0,
            started_at=4.0,
            finished_at=5.0,
            target_name=None,
            log_path=None,
            result_payload={"artifact_path": "/tmp/chrootctl-magisk.zip"},
            progress_detail={"phase": "done", "percent": 100},
        ),
        _JobRecord(
            job_id="e2e-transfer-export",
            kind="transfer",
            title="Fixture transfer export",
            state=JOB_SUCCEEDED,
            progress_text="Archive ready for download",
            created_at=6.0,
            started_at=6.0,
            finished_at=7.0,
            target_name="androidos",
            log_path=log_path,
            result_payload={"archive_name": "androidos.tar.zst", "checksum": "fixture-sha256"},
            progress_detail={"phase": "export", "percent": 100},
            retry={"action": "transfer.export", "payload": {"name": "androidos"}},
        ),
        _JobRecord(
            job_id="e2e-upgrade-running",
            kind="upgrade",
            title="Fixture devbox upgrade",
            state=JOB_RUNNING,
            progress_text="Installing package updates",
            created_at=8.0,
            started_at=8.5,
            finished_at=None,
            target_name="devbox",
            log_path=running_log,
            progress_detail={"phase": "upgrade", "percent": 44},
            retry={"action": "chroot.upgrade", "payload": {"name": "devbox"}},
        ),
        _JobRecord(
            job_id="e2e-repair-queued",
            kind="repair",
            title="Fixture registry repair",
            state=JOB_QUEUED,
            progress_text="Waiting for maintenance slot",
            created_at=9.0,
            started_at=None,
            finished_at=None,
            target_name="rescue",
            log_path=None,
            progress_detail={"phase": "queue", "percent": 0},
            retry={"action": "repair.apply", "payload": {"names": ["rescue"]}},
        ),
        _JobRecord(
            job_id="e2e-snapshot-running",
            kind="snapshot",
            title="Fixture snapshot export",
            state=JOB_RUNNING,
            progress_text="Packing archive",
            created_at=10.0,
            started_at=10.2,
            finished_at=None,
            target_name="androidos",
            log_path=running_log,
            progress_detail={"phase": "archive", "percent": 64},
            retry={"action": "snapshot.export", "payload": {"name": "androidos", "snapshot_name": "snap-good-001"}},
        ),
    ]
    with jobs._lock:
        for record in records:
            jobs._jobs[record.job_id] = record


def install_e2e_fixtures(app) -> None:
    if os.environ.get("CHROOTCTL_E2E_FIXTURES") not in {"1", "true", "yes"}:
        return
    app.state.services = E2EServiceWrapper(app.state.services)
    _seed_jobs(app)
