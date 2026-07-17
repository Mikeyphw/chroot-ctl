from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from chrootctl.base_install import ReleaseRef
from chrootctl.catalog import ManifestEntry
from chrootctl.chroot_users import ChrootUser
from chrootctl.models import (
    CatalogApplyResult,
    CheckRow,
    ChrootArchiveInspection,
    ChrootDetails,
    ChrootRecord,
    ChrootRemovalResult,
    ChrootRenameResult,
    ChrootUserCreateResult,
    ChrootUserDetails,
    ChrootUserPasswordResult,
    ChrootUserRemoveResult,
    ChrootUserShellResult,
    ChrootUserSudoResult,
    DashboardSummary,
    InstallFinalizeResult,
    InstallRunResult,
    InstallWizardDefaults,
    LogEntry,
    LogLink,
    LogSnapshot,
    SessionActionResult,
    UpgradeResult,
    UserIdStatus,
    UserIdSyncResult,
    AuditEvent,
    SupportBundleResult,
)
from chrootctl.web.app import create_app
from chrootctl.web.jobs import JobSnapshot


class FakeSystemService:
    def dashboard(self, *, target_name: str | None = None, details: bool = False, tail: int = 20) -> DashboardSummary:
        return DashboardSummary(
            target_name="work",
            chroots=(
                ChrootRecord(
                    name="work",
                    distro="ubuntu",
                    path="/data/local/tmp/work",
                    release_name="jammy",
                    version="latest",
                    phase="finalize",
                    installed=True,
                    created_at="now",
                    updated_at="now",
                ),
            ),
            status_checks=(CheckRow(check="/proc", result="PASS", detail="mounted", next=""),),
            doctor_checks=(CheckRow(check="busybox", result="PASS", detail="ok", next=""),),
            logs=LogSnapshot(
                log_file=Path("/tmp/chrootctl.log"),
                level=None,
                lines=("booted",),
                target_name="work",
                entries=(LogEntry(line="booted", level="INFO", links=()),),
                related_links=(LogLink(label="Chroot · work", href="/chroots/work"),),
            ),
        )

    def status(self, name: str, *, details: bool = False):
        return [CheckRow(check=name, result="PASS", detail="mounted", next=f"chrootctl --name {name} logs --all")]

    def doctor(self, name: str):
        return [
            CheckRow(check=name, result="PASS", detail="ok", next=""),
            CheckRow(check="sudoers", result="WARN", detail="needs sync", next=f"chrootctl --name {name} users sync-id mike"),
        ]

    def host_doctor(self):
        return [
            CheckRow(check="python_runtime", result="PASS", detail="ready", next=""),
            CheckRow(check="arm64_qemu", result="WARN", detail="qemu-aarch64-static not found", next="Install qemu-aarch64-static"),
        ]

    def cross_arch_state(self):
        return {
            "host_arch": "amd64",
            "targets": [
                {"arch": "amd64", "native": True, "qemu_ready": True, "binfmt_ready": True, "ready": True, "mode": "native", "guidance": "Native host architecture."},
                {"arch": "arm64", "native": False, "qemu_ready": False, "binfmt_ready": False, "ready": False, "mode": "extract-only", "guidance": "Extract now, then export/import to the target device for finalize later."},
            ],
        }

    def foreign_arch_advisories(self):
        return [
            {"name": "work-arm64", "arch": "arm64", "phase": "extract", "installed": "no", "mode": "deferred", "summary": "work-arm64 targets arm64; extract is ready to export and finalize on-device later."}
        ]

    def logs(self, name: str | None, *, tail: int = 100, show_all: bool = False, level: str | None = None, follow: bool = False):
        return LogSnapshot(
            log_file=Path("/tmp/chrootctl.log"),
            level=level,
            lines=(
                "2026-06-18 INFO applied tool tool-one to ubuntu",
                "2026-06-18 ERROR failed for mike in work",
            ),
            follow=follow,
            target_name=name,
            entries=(
                LogEntry(
                    line="2026-06-18 INFO applied tool tool-one to ubuntu",
                    level="INFO",
                    links=(LogLink(label="tool · tool-one", href="/tools/tool-one"),),
                ),
                LogEntry(
                    line="2026-06-18 ERROR failed for mike in work",
                    level="ERROR",
                    links=(),
                ),
            ),
            related_links=(LogLink(label="Chroot · work", href="/chroots/work"),),
        )


class FakeChrootService:
    def list(self):
        return [
            ChrootRecord(
                name="work",
                distro="ubuntu",
                path="/data/local/tmp/work",
                release_name="jammy",
                version="latest",
                phase="finalize",
                installed=True,
                created_at="now",
                updated_at="now",
            )
        ]

    def get(self, name: str):
        return ChrootDetails(
            name=name,
            distro="ubuntu",
            path="/data/local/tmp/work",
            release_name="jammy",
            version="latest",
            phase="finalize",
            installed=True,
            arch="arm64",
            created_at="now",
            updated_at="now",
            configured_mounts="default",
            extra_packages="none",
            locale="en_US.UTF-8",
        )

    def start(self, name: str, *, login: bool = True, root_login: bool = False):
        return SessionActionResult(action="start", target=name, exit_code=0, next_steps=("chrootctl --name work logs --all",))

    def restart(self, name: str, *, login: bool = True, root_login: bool = False):
        return SessionActionResult(action="restart", target=name, exit_code=0, next_steps=("chrootctl --name work logs --all",))

    def rename(self, old_name: str, new_name: str):
        return ChrootRenameResult(old_name=old_name, new_name=new_name, renamed=True)

    def remove(self, name: str):
        return ChrootRemovalResult(name=name, removed=True, unmounted_success=3, unmounted_failed=0)

    def export(self, name: str, *, archive: Path | None = None, password: str | None = None):
        target = archive or Path(f"./{name}.tar.zst")
        Path(target).write_bytes(b"tar.zst")
        checksum_path = Path(f"{target}.sha256")
        checksum_path.write_text("deadbeef  " + Path(target).name + "\n", encoding="utf-8")
        return {"name": name, "archive": str(target), "arch": "arm64", "checksum": "deadbeef", "checksum_path": str(checksum_path)}

    def export_preview(self, name: str, *, archive: Path | None = None):
        return {"ok": True, "kind": "export", "name": name, "archive": str(archive or Path(f"./{name}.tar.zst")), "size_bytes": 12345, "required_bytes": 12345, "free_bytes": 999999, "enough_space": True}

    def import_preview(self, archive: Path, *, name: str | None = None, conflict: str = "rename"):
        return {"ok": True, "kind": "import", "archive": str(archive), "requested_name": name or "imported", "final_name": name or "imported", "conflict": conflict, "target_exists": True, "size_bytes": 12345, "required_bytes": 12345, "free_bytes": 999999, "enough_space": True, "checksum_verified": True}

    def delete_preview(self, name: str):
        return {"ok": True, "kind": "delete", "name": name, "path": f"/data/local/tmp/{name}", "reclaim_bytes": 12345}

    def import_archive(self, archive: Path, *, name: str | None = None, conflict: str = "rename", password: str | None = None, post_import: str = "register"):
        target_name = name or "imported"
        return {"name": target_name, "archive": str(archive), "arch": "arm64", "path": f"/data/local/tmp/{target_name}", "checksum_verified": True, "conflict_strategy": conflict, "post_import_action": post_import}

    def validate_imported(self, name: str):
        return {"ok": True, "summary": "Imported chroot looks ready.", "missing": (), "arch": "arm64", "messages": ()}

    def package_diff(self, left: str, right: str):
        from chrootctl.models import PackageDiffResult
        return PackageDiffResult(left=left, right=right, left_count=3, right_count=4, only_left=("vim",), only_right=("nano", "htop"), common_count=2)

    def validate_imported(self, name: str):
        return {"ok": True, "messages": ("ready",)}

    def inspect_archive(self, archive: Path, *, password: str | None = None):
        return ChrootArchiveInspection(
            archive=archive,
            source_name="work",
            suggested_name="work",
            path_name="work",
            distro="ubuntu",
            arch="arm64",
            release_name="jammy",
            version="latest",
            phase="extract",
            installed=False,
            metadata={"source": "test"},
            size_bytes=12345,
            created_at="2026-06-23T00:00:00+00:00",
            checksum="deadbeef",
            checksum_path=Path(str(archive) + ".sha256"),
            checksum_verified=True,
            target_exists=True,
        )


class FakeUserService:
    def list(self):
        return [ChrootUser(username="mike", uid="1000", gid="1000", home="/home/mike", shell="/bin/bash")]

    def show(self, username: str):
        return ChrootUserDetails(username=username, uid="1000", gid="1000", home="/home/mike", shell="/bin/bash", sudo=True)

    def add(self, username: str, *, shell: str, sudo: bool):
        return ChrootUserCreateResult(username=username, shell=shell, sudo=sudo, created=True)

    def remove(self, username: str, *, delete_home: bool):
        return ChrootUserRemoveResult(username=username, home_deleted=delete_home, removed=True)

    def set_password(self, username: str, *, password: str | None = None):
        return ChrootUserPasswordResult(username=username, updated=True)

    def set_shell(self, username: str, *, shell: str):
        return ChrootUserShellResult(username=username, shell=shell, updated=True)

    def set_sudo(self, username: str, *, enabled: bool):
        return ChrootUserSudoResult(username=username, enabled=enabled)

    def show_id(self, username: str):
        return UserIdStatus(username=username, host_uid=1000, host_gid=1000, chroot_uid="1000", chroot_gid="1000", passwd_exists=True, group_exists=True)

    def sync_id(self, username: str, *, fix_ownership: bool = True):
        return UserIdSyncResult(username=username, uid=1000, gid=1000, ownership_fixed=fix_ownership)


class FakeCatalogService:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def list_entries(self, *, distro: str | None = None, category: str | None = None):
        entries = [
            ManifestEntry(
                kind=self.kind,
                name=f"{self.kind}-one",
                description="demo entry",
                distros=("ubuntu",),
                categories=("dev",),
                script=f"{self.kind}-one.sh",
                script_text="echo ok",
            ),
            ManifestEntry(
                kind=self.kind,
                name=f"{self.kind}-two",
                description="second entry",
                distros=("arch", "ubuntu"),
                categories=("desktop",),
                script=f"{self.kind}-two.sh",
                script_text="echo second",
            ),
        ]
        filtered = entries
        if distro is not None:
            filtered = [entry for entry in filtered if distro in entry.distros]
        if category is not None:
            filtered = [entry for entry in filtered if category in entry.categories]
        return filtered

    def categories(self, *, distro: str | None = None):
        values = {"dev", "desktop"}
        if distro == "ubuntu":
            return sorted(values)
        return sorted(values)

    def get_entry(self, name: str):
        for entry in self.list_entries():
            if entry.name == name:
                return entry
        raise KeyError(name)

    def apply(self, names, *, progress=None):
        if progress is not None:
            progress(f"Applying {self.kind}")
        return [CatalogApplyResult(kind=self.kind, name=names[0], distro="ubuntu", categories=("dev",), applied=True)]


class FakeInstallService:
    def wizard_defaults(self, *, name: str | None = None, distro: str | None = None):
        return InstallWizardDefaults(distro=distro or "ubuntu", name=name or "work", username="mike", preset="development", profile="dev")

    def distros(self):
        return ("ubuntu", "arch")

    def profiles(self):
        return ("minimal", "dev")

    def desktops(self):
        return ("auto", "none")

    def list_target_users(self, *, name: str | None = None):
        return [{"username": "mike", "uid": "1000", "gid": "1000", "home": "/home/mike", "shell": "/bin/bash"}]

    def mirror_options(self, distro: str | None = None):
        return [{"id": "auto", "label": "Auto-select", "healthy": True}, {"id": "archive.ubuntu.com", "label": "Ubuntu archive", "healthy": True}]

    def preset_options(self, distro: str | None = None):
        return [{"id": "development", "label": "Development", "profile": "dev", "desktop": "none"}]

    def compatibility_matrix(self, distro: str | None = None):
        return {"distro": distro or "ubuntu", "releases": ["noble"], "profiles": ["minimal", "dev"], "desktops": {"minimal": ["none"], "dev": ["none"]}}

    def install_form_state(self, *, name: str | None = None, distro: str | None = None):
        return {
            "defaults": {"distro": distro or "ubuntu", "name": name or "work", "username": "mike", "preset": "development", "profile": "dev", "desktop": "none", "mirror": "auto"},
            "distros": [{"id": "ubuntu", "label": "Ubuntu"}, {"id": "arch", "label": "Arch"}],
            "profiles": [{"id": "minimal", "label": "Minimal", "desktop_allowed": False, "default_desktop": "none"}],
            "desktops": [{"id": "none", "label": "None", "lightweight": False, "packages": ()}],
            "presets": [{"id": "development", "label": "Development", "profile": "dev", "desktop": "none"}],
            "compatibility": {"distro": distro or "ubuntu", "releases": ["noble"], "profiles": ["minimal", "dev"], "desktops": {"minimal": ["none"], "dev": ["none"]}},
            "mirrors": self.mirror_options(distro),
            "users": self.list_target_users(name=name),
            "requirements": {"username_required": True, "root_required": True},
            "rules": {"minimal_forces_desktop": "none"},
        }

    def validate_install_submission(self, request):
        if not request.username:
            return {
                "ok": False,
                "blocking": [{"code": "missing_username", "message": "No target user selected."}],
                "warnings": [],
                "resolved": [],
                "plan": None,
                "users": self.list_target_users(name=request.name),
                "requirements": {"username_required": True},
            }
        return {
            "ok": True,
            "blocking": [],
            "warnings": [],
            "resolved": [],
            "plan": {
                "name": request.name,
                "distro": request.distro,
                "username": request.username,
                "preset": request.preset,
                "profile": request.profile or "minimal",
                "requested_desktop": request.desktop or "auto",
                "desktop": request.desktop or "none",
                "release": request.release or "auto",
                "version": request.version or "latest",
                "mirror": request.mirror or "auto",
                "tools": list(request.tools),
                "addons": list(request.addons),
                "repair": request.repair,
                "steps": [{"id": "validate", "label": "Validate request", "description": "Check request"}],
                "total_steps": 1,
                "warnings": [],
            },
            "users": self.list_target_users(name=request.name),
            "requirements": {"username_required": True},
        }

    def preview_install(self, request):
        result = self.validate_install_submission(request)
        result["preview"] = {
            "storage": {"required_bytes": 1024 * 1024 * 512, "free_bytes": 1024 * 1024 * 2048, "enough_space": True},
            "mirror": {"selection": request.mirror or "auto", "fallback_chain": ["archive.ubuntu.com", "ports.ubuntu.com"]},
            "dry_run": {"supported": True},
        }
        return result

    def list_versions(self, *, distro: str, name: str | None = None, username: str | None = None):
        return [ReleaseRef(label="24.04", url="https://example.invalid/24.04.tar.xz")]

    def install(self, request, *, progress=None):
        if progress is not None:
            progress("Completed phase: finalize")
        return InstallRunResult(
            chroot_name=request.name,
            distro=request.distro,
            phases=(InstallFinalizeResult(installed=True, uid_sync=True, snapshot="none"),),
            tool_results=(CatalogApplyResult(kind="tool", name="tool-one", distro="ubuntu", categories=("dev",), applied=True),),
            addon_results=(),
            next_steps=("chrootctl --name work start",),
        )

    def upgrade(self, name: str, *, username: str | None = None, progress=None):
        if progress is not None:
            progress("Upgrade completed")
        return UpgradeResult(status="ok", snapshot="snap-1", next_steps=("chrootctl --name work restart",))



class FakeAuditService:
    def recent(self, limit: int = 20):
        return [
            AuditEvent(
                event_id=1,
                event_type="transfer.export",
                actor="mike",
                target="work",
                result="ok",
                message="Exported work.tar.zst",
                created_at="now",
                metadata={"encrypted": "False"},
            )
        ][:limit]

    def record(self, event_type: str, *, target: str = "", result: str = "ok", message: str = "", actor: str | None = None, metadata: dict[str, str] | None = None):
        return AuditEvent(
            event_id=2,
            event_type=event_type,
            actor=actor or "mike",
            target=target,
            result=result,
            message=message,
            created_at="now",
            metadata=metadata or {},
        )


class FakeSupportService:
    def export_bundle(self, archive=None, *, jobs=None):
        bundle = Path("/tmp/chrootctl-support-bundle.tar.gz")
        bundle.write_text("bundle", encoding="utf-8")
        return SupportBundleResult(archive=bundle, included=("manifest.json",))




class FakeRepairService:
    def preview_registry_repair(self):
        from chrootctl.models import RegistryRepairResult
        return RegistryRepairResult(
            scanned_paths=1,
            missing_records=("orphan",),
            missing_paths=("missing",),
            mismatched_paths=(),
            preview=True,
            next_steps=("Run repair",),
        )

    def preview_items(self):
        return [
            {
                "item_id": "chroot:orphan",
                "name": "orphan",
                "kind": "missing-record",
                "severity": "warn",
                "action": "register",
                "path": "/data/chroots/orphan",
                "expected_path": "",
                "summary": "Filesystem path exists without a registry record.",
                "impact": "Register the orphaned chroot.",
                "current_state": "No registry record exists.",
                "proposed_state": "Create a recovered registry record.",
                "diff_lines": ["- registry[orphan] = missing", "+ registry[orphan].path = /data/chroots/orphan"],
            }
        ]

    def preview_plan(self, decisions):
        selected = [item for item in self.preview_items() if any(decision.get("item_id") == item["item_id"] for decision in decisions)]
        return {
            "ok": bool(selected),
            "summary": {
                "selected_count": len(selected),
                "register_count": len(selected),
                "fix_path_count": 0,
                "remove_record_count": 0,
                "skip_count": 0,
                "warnings": ["Recovered chroots may need metadata review after registration."] if selected else [],
                "next_steps": ["Queue the repair job and review the result on the Jobs page."] if selected else ["Select at least one repair action to continue."],
            },
            "selected": selected,
        }

    def apply_registry_repair(self):
        from chrootctl.models import RegistryRepairResult
        return RegistryRepairResult(
            scanned_paths=1,
            repaired_records=("orphan",),
            removed_records=("missing",),
            preview=False,
            next_steps=("Open dashboard",),
        )

    def apply_registry_repair_plan(self, decisions):
        return self.apply_registry_repair()


class FakeSnapshotService:
    def list(self, *, chroot_name: str | None = None, limit: int = 20):
        from chrootctl.models import SnapshotRecord
        if chroot_name == "work":
            return [
                SnapshotRecord(
                    snapshot_id=1,
                    name="snap-001",
                    chroot_name="work",
                    path="/data/chroots/.snapshots/work/snap-001",
                    kind="copy",
                    created_at="now",
                    note="",
                    size_bytes=0,
                    metadata={},
                )
            ][:limit]
        return []

    def restore(self, chroot_name: str, snapshot_name: str):
        return {"ok": True, "chroot_name": chroot_name, "snapshot_name": snapshot_name, "next_steps": ("Open shell",)}


class FakeServices:
    def __init__(self):
        self._install = FakeInstallService()
        self._repair = FakeRepairService()

    class _Runner:
        def host_arch(self):
            return "amd64"

        def can_execute_foreign_arch(self, arch: str):
            return arch == "arm64"

    class _Runtime:
        def __init__(self):
            self.runner = FakeServices._Runner()

    def system(self):
        return FakeSystemService()

    def chroots(self):
        return FakeChrootService()

    def users(self, *, name: str | None = None):
        return FakeUserService()

    def catalog(self, kind: str, *, name: str | None = None):
        return FakeCatalogService(kind)

    def install(self):
        return self._install

    def runtime_for(self, name: str | None = None, *, username: str | None = None):
        return FakeServices._Runtime()

    def audit(self):
        return FakeAuditService()

    def support(self):
        return FakeSupportService()

    def repair(self):
        return self._repair

    def snapshots(self):
        return FakeSnapshotService()


class FakeJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, JobSnapshot] = {}
        self.counter = 0

    def submit(self, *, kind: str, title: str, runner, target_name: str | None = None, log_path=None, retry=None):
        self.counter += 1
        job_id = str(self.counter)
        holder = {"text": "Queued"}

        def progress(text: str) -> None:
            holder["text"] = text

        error = None
        state = "succeeded"
        try:
            result = runner(progress)
        except Exception as exc:
            result = None
            error = str(exc)
            state = "failed"
        snapshot = JobSnapshot(
            job_id=job_id,
            kind=kind,
            title=title,
            state=state,
            progress_text=holder["text"],
            created_at=0.0,
            started_at=0.0,
            finished_at=1.0,
            target_name=target_name,
            log_path=log_path,
            result_payload=result,
            error=error,
            next_steps=tuple(getattr(result, "next_steps", ())) if result is not None else (),
            log_lines=("line one", "line two"),
            retry=retry,
        )
        self.jobs[job_id] = snapshot
        return snapshot

    def get(self, job_id: str, *, tail: int = 50):
        return self.jobs[job_id]

    def list_recent(self, *, limit: int = 10, tail: int = 10, target_name: str | None = None, log_path=None):
        items = list(self.jobs.values())
        if target_name is not None:
            items = [job for job in items if job.target_name == target_name]
        if log_path is not None:
            items = [job for job in items if job.log_path == log_path]
        return items[:limit]

    def event_payload(self, job_id: str, *, tail: int = 50):
        return self.jobs[job_id].to_event_payload()


def build_client(tmp_path: Path, *, raise_server_exceptions: bool = True) -> TestClient:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        (
            "{"
            f"\"database_path\": \"{tmp_path / 'registry.sqlite3'}\", "
            f"\"log_file\": \"{tmp_path / 'chrootctl.log'}\", "
            f"\"chroot_root\": \"{tmp_path / 'chroots'}\""
            "}"
        ),
        encoding="utf-8",
    )
    app = create_app(config_path=config_path, dry_run=True)
    app.state.services = FakeServices()
    app.state.jobs = FakeJobs()
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)



def csrf_token(client: TestClient, path: str = "/") -> str:
    response = client.get(path)
    assert response.status_code == 200
    token = client.cookies.get("chrootctl_csrf")
    assert token
    return token


def post_with_csrf(client: TestClient, path: str, *, data: dict[str, object] | None = None, page: str = "/", follow_redirects: bool = False):
    token = csrf_token(client, page)
    payload = dict(data or {})
    payload["csrf_token"] = token
    return client.post(path, data=payload, follow_redirects=follow_redirects)




def test_host_doctor_page_and_api_render(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    page = client.get("/doctor/host")
    assert page.status_code == 200
    assert "Host readiness checks" in page.text
    assert "Finalize on device later" in page.text

    api = client.get("/api/doctor/host")
    assert api.status_code == 200
    payload = api.json()
    assert payload["host_arch"] == "amd64"
    assert payload["summary"]["warn"] >= 1
    assert payload["advisories"][0]["name"] == "work-arm64"


def test_transfer_page_shows_cross_arch_handoff(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    page = client.get("/transfer")
    assert page.status_code == 200
    assert "Finalize on device later" in page.text
    assert "work-arm64" in page.text
    temp_api = client.get("/api/transfer/temp")
    assert temp_api.status_code == 200


def test_dashboard_route_renders(tmp_path: Path) -> None:
    client = build_client(tmp_path, raise_server_exceptions=False)
    response = client.get("/")
    assert response.status_code == 200
    assert "Installed chroots" in response.text
    assert "running" in response.text
    assert "Recent jobs" in response.text


def test_chroot_and_user_routes_render(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    assert client.get("/chroots").status_code == 200
    detail = client.get("/chroots/work")
    assert detail.status_code == 200
    assert "configured_mounts" in detail.text
    assert "Open confirmation" in detail.text

    users = client.get("/chroots/work/users")
    assert users.status_code == 200
    assert "Add user" in users.text

    user = client.get("/chroots/work/users/mike")
    assert user.status_code == 200
    assert "Set password" in user.text
    assert "Run users sync-id" in user.text


def test_user_actions_queue_jobs(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    add = post_with_csrf(client, "/chroots/work/users", page="/chroots/work/users", data={"username": "alice", "shell": "/bin/zsh", "sudo": "true"}, follow_redirects=False)
    assert add.status_code == 303

    password = post_with_csrf(
        client,
        "/chroots/work/users/mike/password",
        page="/chroots/work/users/mike",
        data={"password": "secret123", "confirm_password": "secret123", "confirm_username": "mike"},
        follow_redirects=False,
    )
    assert password.status_code == 303

    sudo = post_with_csrf(client, "/chroots/work/users/mike/sudo", page="/chroots/work/users/mike", data={"enabled": "false"}, follow_redirects=False)
    assert sudo.status_code == 303

    shell = post_with_csrf(client, "/chroots/work/users/mike/shell", page="/chroots/work/users/mike", data={"shell": "/bin/zsh"}, follow_redirects=False)
    assert shell.status_code == 303

    sync_id = post_with_csrf(client, "/chroots/work/users/mike/sync-id", page="/chroots/work/users/mike", data={"fix_ownership": "true"}, follow_redirects=False)
    assert sync_id.status_code == 303

    remove = post_with_csrf(
        client,
        "/chroots/work/users/mike/remove",
        page="/chroots/work/users/mike",
        data={"confirm_username": "mike", "delete_home": "true"},
        follow_redirects=False,
    )
    assert remove.status_code == 303


def test_system_and_catalog_routes_render(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    status = client.get("/status", params={"name": "work"})
    assert status.status_code == 200
    assert "Open logs" in status.text
    doctor = client.get("/doctor")
    assert doctor.status_code == 200
    assert "PASS / WARN / FAIL" in doctor.text
    assert "Open user" in doctor.text
    logs = client.get("/logs", params={"name": "work", "level": "ERROR"})
    assert logs.status_code == 200
    assert "/tmp/chrootctl.log" in logs.text
    assert "Follow live" in logs.text
    assert "/chroots/work" in logs.text
    assert "/tools/tool-one" in logs.text

    log_events = client.get("/logs/events", params={"name": "work", "level": "ERROR", "follow": "false"})
    assert log_events.status_code == 200
    assert "tool-one" in log_events.text
    assert "failed for mike in work" in log_events.text

    tools = client.get("/tools", params={"q": "demo", "category": "dev", "selected": "tool-one"})
    assert tools.status_code == 200
    assert "Preview · tool-one" in tools.text
    assert "echo ok" in tools.text

    addons = client.get("/addons", params={"selected": "addon-one"})
    assert addons.status_code == 200
    assert "Preview · addon-one" in addons.text

    tool_detail = client.get("/tools/tool-one")
    assert tool_detail.status_code == 200
    assert "Apply tool-one" in tool_detail.text

    addon_detail = client.get("/addons/addon-one")
    assert addon_detail.status_code == 200
    assert "Apply addon-one" in addon_detail.text




def test_system_api_routes_return_structured_payload(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    status = client.get("/api/status", params={"name": "work"})
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["name"] == "work"
    assert status_data["rows"][0]["next_href"] == "/logs?name=work"

    doctor = client.get("/api/doctor")
    assert doctor.status_code == 200
    doctor_data = doctor.json()
    assert doctor_data["name"] == "work"
    assert doctor_data["summary"]["warn"] == 1
    assert doctor_data["rows"][1]["next_href"] == "/chroots/work/users/mike"

    chroots = client.get("/api/chroots")
    assert chroots.status_code == 200
    assert chroots.json()["items"][0]["name"] == "work"

    snapshot = client.get("/api/logs", params={"name": "work", "level": "error", "follow": "false"})
    assert snapshot.status_code == 200
    data = snapshot.json()
    assert data["snapshot"]["log_file"] == "/tmp/chrootctl.log"
    assert data["snapshot"]["level"] == "ERROR"
    assert data["snapshot"]["entries"][0]["links"][0]["href"] == "/tools/tool-one"
    assert data["recent_jobs"] == []



    install_options = client.get("/api/install/options", params={"distro": "ubuntu"})
    assert install_options.status_code == 200
    assert install_options.json()["requirements"]["username_required"] is True

    install_validate = client.post(
        "/api/install/validate",
        headers={"x-csrf-token": csrf_token(client, "/install")},
        json={"distro": "ubuntu", "name": "work", "username": "mike", "profile": "dev", "desktop": "none"},
    )
    assert install_validate.status_code == 200
    assert install_validate.json()["ok"] is True

    events = client.get("/api/logs/events", params={"name": "work", "level": "error", "follow": "false"})
    assert events.status_code == 200
    assert '"snapshot"' in events.text
    assert '"ERROR"' in events.text
    assert '"/tmp/chrootctl.log"' in events.text

def test_install_submit_queues_job_and_job_page_renders(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    page = client.get("/install", params={"distro": "ubuntu"})
    assert page.status_code == 200
    assert "Queue a guided install job" in page.text
    response = post_with_csrf(
        client,
        "/install",
        page="/install?distro=ubuntu",
        data={
            "distro": "ubuntu",
            "name": "work",
            "username": "mike",
            "profile": "dev",
            "desktop": "auto",
            "release": "jammy",
            "version": "https://example.invalid/24.04.tar.xz",
            "tools": ["tool-one"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    job_page = client.get(response.headers["location"])
    assert "Install work" in job_page.text
    assert "Recent log lines" in job_page.text
    job_api = client.get("/api/jobs/1")
    assert job_api.status_code == 200
    assert job_api.json()["job_id"] == "1"
    assert job_api.json()["state"] == "succeeded"
    events = client.get("/jobs/1/events")
    assert events.status_code == 200
    assert "Completed phase: finalize" in events.text


def test_chroot_actions_and_catalog_apply_queue_jobs(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = post_with_csrf(client, "/chroots/work/start", page="/chroots/work", follow_redirects=False)
    assert response.status_code == 303
    rename = post_with_csrf(client, "/chroots/work/rename", page="/chroots/work", data={"new_name": "devbox", "confirm_name": "work"}, follow_redirects=False)
    assert rename.status_code == 303
    remove = post_with_csrf(client, "/chroots/work/remove", page="/chroots/work", data={"confirm_name": "work"}, follow_redirects=False)
    assert remove.status_code == 303
    tools = post_with_csrf(client, "/tools/apply", page="/tools", data={"name": "work", "entries": ["tool-one", "tool-two"]}, follow_redirects=False)
    assert tools.status_code == 303
    addons = post_with_csrf(client, "/addons/apply", page="/addons", data={"name": "work", "entries": ["addon-one"]}, follow_redirects=False)
    assert addons.status_code == 303


def test_install_validate_blocks_missing_username(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.post(
        "/api/install/validate",
        headers={"x-csrf-token": csrf_token(client, "/install")},
        json={"distro": "ubuntu", "name": "work", "username": "", "profile": "dev", "desktop": "none"},
    )
    assert response.status_code == 400
    payload = response.json()["error"]
    assert payload["code"] == "install_validation_failed"
    assert payload["details"]["blocking"][0]["code"] == "missing_username"
    assert payload["retryable"] is True


def test_install_submit_blocks_missing_username(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = post_with_csrf(
        client,
        "/install",
        page="/install?distro=ubuntu",
        data={
            "distro": "ubuntu",
            "name": "work",
            "username": "",
            "profile": "dev",
            "desktop": "auto",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "No target user selected." in response.text


def test_failed_job_page_shows_friendly_error_and_copy_logs(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    client.app.state.jobs.jobs["99"] = JobSnapshot(
        job_id="99",
        kind="install",
        title="Install work",
        state="failed",
        progress_text="Installer failed",
        created_at=0.0,
        started_at=0.0,
        finished_at=1.0,
        target_name="work",
        log_path=Path("/tmp/chrootctl.log"),
        error="RuntimeError: Choose user: no non-root users available; pass --username",
        next_steps=("Open installer",),
        log_lines=("2026-06-18 ERROR missing username",),
    )
    response = client.get("/jobs/99")
    assert response.status_code == 200
    assert "Failure summary" in response.text
    assert "Copy logs" in response.text
    assert "friendly-error-card" in response.text
    assert "Missing target user" in response.text or "Install failed" in response.text


class BrokenInstallService(FakeInstallService):
    def mirror_options(self, distro: str | None = None):
        return [{"id": "auto", "label": "Auto-select", "healthy": True}, {"id": "archive.ubuntu.com", "label": "Ubuntu archive", "healthy": True}]

    def preset_options(self, distro: str | None = None):
        return [{"id": "development", "label": "Development", "profile": "dev", "desktop": "none"}]

    def compatibility_matrix(self, distro: str | None = None):
        return {"distro": distro or "ubuntu", "releases": ["noble"], "profiles": ["minimal", "dev"], "desktops": {"minimal": ["none"], "dev": ["none"]}}

    def install_form_state(self, *, name: str | None = None, distro: str | None = None):
        raise RuntimeError("missing runtime")

    def wizard_defaults(self, *, name: str | None = None, distro: str | None = None):
        return InstallWizardDefaults(distro=distro or "ubuntu", name=name or "work", username=None, profile="minimal", desktop="none")


class BrokenSystemService(FakeSystemService):
    def dashboard(self, *, target_name: str | None = None, details: bool = False, tail: int = 20):
        raise RuntimeError("dashboard failed")


class BrokenServices(FakeServices):
    def system(self):
        return BrokenSystemService()

    def install(self):
        return BrokenInstallService()


def build_broken_client(tmp_path: Path) -> TestClient:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        (
            "{"
            f"\"database_path\": \"{tmp_path / 'registry.sqlite3'}\", "
            f"\"log_file\": \"{tmp_path / 'chrootctl.log'}\", "
            f"\"chroot_root\": \"{tmp_path / 'chroots'}\""
            "}"
        ),
        encoding="utf-8",
    )
    app = create_app(config_path=config_path, dry_run=True)
    app.state.services = BrokenServices()
    app.state.jobs = FakeJobs()
    return TestClient(app)


def test_install_page_handles_missing_runtime_without_500(tmp_path: Path) -> None:
    client = build_broken_client(tmp_path)
    response = client.get("/install?distro=ubuntu&name=work")
    assert response.status_code == 200
    assert "Queue a guided install job" in response.text
    assert "No non-root users found" in response.text or "Target user" in response.text


def test_dashboard_handles_summary_failure_without_500(tmp_path: Path) -> None:
    client = build_broken_client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Ready to install?" in response.text


def test_transfer_page_and_api_inspect_archive(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    page = client.get("/transfer")
    assert page.status_code == 200
    assert "Export, inspect, and import tar.zst chroots" in page.text

    inspect_response = post_with_csrf(
        client,
        "/transfer/inspect",
        page="/transfer",
        data={"archive": str(tmp_path / "work.tar.zst")},
        follow_redirects=True,
    )
    assert inspect_response.status_code == 200
    assert "Archive summary" in inspect_response.text
    assert "work" in inspect_response.text

    api_response = client.get("/api/transfer/inspect", params={"archive": str(tmp_path / "work.tar.zst")})
    assert api_response.status_code == 200
    assert api_response.json()["source_name"] == "work"

    readiness = client.get("/api/transfer/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["host_arch"] == "amd64"


def test_transfer_download_and_upload_endpoints(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    download = client.get("/transfer/download/work")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/zstd")
    assert "attachment; filename=" in download.headers.get("content-disposition", "")
    assert download.content == b"tar.zst"

    inspect_upload = client.post(
        "/transfer/inspect-upload",
        data={"csrf_token": csrf_token(client, "/transfer")},
        files={"archive_file": ("upload.tar.zst", b"archive-bytes", "application/zstd")},
        follow_redirects=True,
    )
    assert inspect_upload.status_code == 200
    assert "Archive summary" in inspect_upload.text
    assert "upload.tar.zst" in inspect_upload.text or "work" in inspect_upload.text

    import_upload = client.post(
        "/transfer/import-upload",
        data={"csrf_token": csrf_token(client, "/transfer"), "import_name": "phone-copy"},
        files={"archive_file": ("phone-copy.tar.zst", b"archive-bytes", "application/zstd")},
        follow_redirects=False,
    )
    assert import_upload.status_code == 303
    assert "/jobs/" in import_upload.headers["location"]


def test_transfer_page_shows_recent_status_card(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    post_with_csrf(
        client,
        "/transfer/export",
        page="/transfer",
        data={"name": "work", "archive": str(tmp_path / "work.tar.zst")},
        follow_redirects=False,
    )
    page = client.get("/transfer")
    assert page.status_code == 200
    assert "Latest transfer jobs" in page.text
    assert "Export chroot work" in page.text
    assert "Open job" in page.text


def test_transfer_page_cleans_up_stale_temp_archives(tmp_path: Path, monkeypatch) -> None:
    from chrootctl.web.routes import transfer as transfer_routes

    monkeypatch.setattr(transfer_routes.tempfile, "gettempdir", lambda: str(tmp_path))
    transfer_dir = tmp_path / "chrootctl-webui-transfer"
    transfer_dir.mkdir(parents=True, exist_ok=True)

    stale = transfer_dir / "stale.tar.zst"
    stale.write_bytes(b"old")
    fresh = transfer_dir / "fresh.tar.zst"
    fresh.write_bytes(b"new")

    cutoff = 1_700_000_000.0
    monkeypatch.setattr(transfer_routes.time, "time", lambda: cutoff)
    stale_age = cutoff - (transfer_routes._TRANSFER_MAX_AGE_SECONDS + 10)
    fresh_age = cutoff - 60
    import os
    os.utime(stale, (stale_age, stale_age))
    os.utime(fresh, (fresh_age, fresh_age))

    client = build_client(tmp_path)
    page = client.get("/transfer")
    assert page.status_code == 200
    assert not stale.exists()
    assert fresh.exists()
    assert "Temporary transfer files" in page.text


def test_api_validation_error_is_structured(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.post(
        "/api/install/validate",
        headers={"x-csrf-token": csrf_token(client, "/install")},
        json={"distro": "ubuntu", "name": "work", "username": "", "profile": "minimal", "desktop": "none"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "install_validation_failed"
    assert payload["error"]["title"] == "Install validation failed"
    assert payload["error"]["retryable"] is True


def test_docs_page_and_openapi_render(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    docs_page = client.get("/docs")
    assert docs_page.status_code == 200
    assert "API docs and examples" in docs_page.text
    openapi = client.get("/api/openapi.json")
    assert openapi.status_code == 200
    schema = openapi.json()
    assert schema["info"]["title"] == "chrootctl Web UI"
    assert "/api/install/validate" in schema["paths"]


def test_html_routes_degrade_to_error_page(tmp_path: Path) -> None:
    client = build_client(tmp_path, raise_server_exceptions=False)

    class BrokenSystemService(FakeSystemService):
        def dashboard(self, *, target_name: str | None = None, details: bool = False, tail: int = 20):
            raise RuntimeError("boom")

    class BrokenServices(FakeServices):
        def system(self):
            return BrokenSystemService()

        def chroots(self):
            raise RuntimeError("cannot list chroots")

    client.app.state.services = BrokenServices()
    response = client.get("/chroots")
    assert response.status_code == 500
    assert "Request failed" in response.text
    assert "Internal error" in response.text


def test_jobs_page_and_api_routes_render(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    jobs_page = client.get("/jobs")
    assert jobs_page.status_code == 200
    assert "Recent jobs" in jobs_page.text or "Jobs" in jobs_page.text

    queued = post_with_csrf(client, "/transfer/export", page="/transfer", data={"name": "work", "archive": str(tmp_path / "work.tar.zst")}, follow_redirects=False)
    assert queued.status_code == 303

    jobs_api = client.get("/api/jobs?limit=6&tail=5")
    assert jobs_api.status_code == 200
    payload = jobs_api.json()
    assert "items" in payload
    assert isinstance(payload["items"], list)
    assert payload["items"]
    job_id = payload["items"][0]["job_id"]

    detail_api = client.get(f"/api/jobs/{job_id}")
    assert detail_api.status_code == 200
    detail_payload = detail_api.json()
    assert detail_payload["job_id"] == job_id

    logs_api = client.get(f"/api/jobs/{job_id}/logs?tail=5")
    assert logs_api.status_code == 200
    logs_payload = logs_api.json()
    assert logs_payload["job_id"] == job_id
    assert "lines" in logs_payload


def test_transfer_page_shows_checksum_and_conflict_controls(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = post_with_csrf(client, "/transfer/inspect", page="/transfer", data={"archive": "/tmp/work.tar.zst"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Checksum" in response.text
    assert "Conflict handling" in response.text
    assert "existing chroot detected" in response.text


def test_transfer_temp_delete_actions_work(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    temp_dir = Path(__import__("tempfile").gettempdir()) / "chrootctl-webui-transfer"
    temp_dir.mkdir(parents=True, exist_ok=True)
    sample = temp_dir / "sample.tar.zst"
    sample.write_bytes(b"abc")
    sample_checksum = temp_dir / "sample.tar.zst.sha256"
    sample_checksum.write_text("deadbeef  sample.tar.zst\n", encoding="utf-8")

    delete_response = post_with_csrf(client, "/transfer/temp/delete", page="/transfer", data={"path": str(sample)}, follow_redirects=False)
    assert delete_response.status_code == 303
    assert not sample.exists()
    assert not sample_checksum.exists()

    sample2 = temp_dir / "sample2.tar.zst"
    sample2.write_bytes(b"abc")
    clear_response = post_with_csrf(client, "/transfer/temp/clear", page="/transfer", data={}, follow_redirects=False)
    assert clear_response.status_code == 303
    assert not sample2.exists()


def test_install_preview_includes_storage_and_mirror(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    token = csrf_token(client, "/install")
    response = client.post(
        "/api/install/preview",
        json={
            "distro": "ubuntu",
            "name": "work",
            "username": "mike",
            "profile": "dev",
            "desktop": "none",
            "mirror": "auto",
        },
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["preview"]["storage"]["enough_space"] is True
    assert payload["preview"]["mirror"]["selection"] == "auto"


def test_transfer_temp_api_lists_and_deletes_cached_archives(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    token = csrf_token(client, "/transfer")
    transfer_dir = Path(__import__("tempfile").gettempdir()) / "chrootctl-webui-transfer"
    transfer_dir.mkdir(parents=True, exist_ok=True)
    target = transfer_dir / "cached.tar.zst"
    target.write_bytes(b"demo")
    response = client.get("/api/transfer/temp")
    assert response.status_code == 200
    assert any(item["name"] == "cached.tar.zst" for item in response.json()["items"])

    delete_response = client.request("DELETE", "/api/transfer/temp", params={"path": str(target)}, headers={"x-csrf-token": token})
    assert delete_response.status_code == 200
    assert delete_response.json()["removed"] == 1
    assert not target.exists()


def test_transfer_preview_routes_return_estimates(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    archive = tmp_path / "preview.tar.zst"
    archive.write_bytes(b"archive")
    response = client.get("/api/transfer/preview/export", params={"name": "work"})
    assert response.status_code == 200
    assert response.json()["kind"] == "export"

    response = client.get("/api/transfer/preview/import", params={"archive": str(archive), "name": "imported", "conflict": "rename"})
    assert response.status_code == 200
    assert response.json()["kind"] == "import"

    response = client.get("/api/transfer/preview/delete", params={"name": "work"})
    assert response.status_code == 200
    assert response.json()["kind"] == "delete"


def test_transfer_page_uses_async_temp_archive_api(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/transfer")
    assert response.status_code == 200
    body = response.text
    assert 'id="transfer-temp-clear"' in body
    assert 'transfer-temp-delete' in body
    assert '/api/transfer/temp' in body
    assert 'fetch(`/api/transfer/temp?' in body


def test_install_options_include_presets_and_compatibility() -> None:
    client = TestClient(create_app())
    response = client.get("/api/install/options?distro=ubuntu")
    assert response.status_code == 200
    data = response.json()
    assert any(item["id"] == "development" for item in data["presets"])
    assert data["compatibility"]["distro"] == "ubuntu"


def test_install_page_renders_preset_and_compatibility() -> None:
    client = TestClient(create_app())
    response = client.get("/install")
    assert response.status_code == 200
    assert "Backend compatibility matrix" in response.text
    assert "Preset" in response.text


def test_doctor_host_includes_cross_arch_blockers() -> None:
    client = TestClient(create_app())
    response = client.get("/api/doctor/host")
    assert response.status_code == 200
    data = response.json()
    assert "blockers" in data


def test_build_page_renders() -> None:
    client = TestClient(create_app())
    response = client.get("/build")
    assert response.status_code == 200
    assert "Build Magisk ZIP" in response.text


def test_build_module_queues_job_and_exposes_download(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = post_with_csrf(
        client,
        "/build/module",
        data={"include_all_installed": "true", "selected_names": "work"},
        page="/build",
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/jobs/")
    job_id = location.split("/jobs/", 1)[1].split("?", 1)[0]
    page = client.get(location)
    assert page.status_code == 200
    assert "Download artifact" in page.text
    artifact = client.get(f"/build/artifacts/{job_id}")
    assert artifact.status_code == 200
    assert artifact.headers["content-type"].startswith("application/zip")


def test_support_page_loads(tmp_path: Path):
    client = build_client(tmp_path)
    response = client.get("/support")
    assert response.status_code == 200
    assert "Support bundle" in response.text
    assert "transfer.export" in response.text


def test_faq_page_loads(tmp_path: Path):
    client = build_client(tmp_path)
    response = client.get("/faq")
    assert response.status_code == 200
    assert "FAQ and troubleshooting" in response.text


def test_api_events_and_support_bundle(tmp_path: Path):
    client = build_client(tmp_path)
    events_response = client.get("/api/events")
    assert events_response.status_code == 200
    assert events_response.json()["items"][0]["event_type"] == "transfer.export"

    bundle_response = post_with_csrf(client, "/api/support-bundle", page="/support")
    assert bundle_response.status_code == 200
    assert bundle_response.json()["archive"].endswith(".tar.gz")


def test_chroots_page_renders_package_diff_and_shell_copy() -> None:
    app = create_app(dry_run=True)
    app.state.services = FakeServices()
    client = TestClient(app)
    response = client.get("/chroots?left=work&right=work")
    assert response.status_code == 200
    assert "Package diff" in response.text
    assert "Copy shell" in response.text


def test_api_chroots_diff_returns_structured_payload() -> None:
    app = create_app(dry_run=True)
    app.state.services = FakeServices()
    client = TestClient(app)
    response = client.get("/api/chroots/diff", params={"left": "work", "right": "work"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["left"] == "work"
    assert "only_left" in payload


def test_transfer_page_renders_post_import_actions() -> None:
    app = create_app(dry_run=True)
    app.state.services = FakeServices()
    client = TestClient(app)
    response = client.get("/transfer")
    assert response.status_code == 200
    assert "Post-import action" in response.text
    assert "Validate imported rootfs" in response.text


def test_validate_import_api_and_detail_card_render(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    api = client.get("/api/chroots/validate-import/work")
    assert api.status_code == 200
    payload = api.json()
    assert payload["name"] == "work"
    assert payload["validation"]["ok"] is True
    detail = client.get("/chroots/work")
    assert detail.status_code == 200
    assert "Imported chroot integrity" in detail.text
    assert "Copy validate command" in detail.text


def test_manage_source_parser_supports_e2e_command() -> None:
    import manage_source

    parser = manage_source.build_parser()
    args = parser.parse_args(["e2e", "--runner", "npx", "--", "--grep", "transfer"])
    assert args.command == "e2e"
    assert args.runner == "npx"


def test_quickstart_page_loads(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/quickstart")
    assert response.status_code == 200
    assert "Quick start" in response.text
    assert "Install a chroot and start using it" in response.text


def test_dashboard_shows_quickstart_cta(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Open quick start" in response.text


def test_chroot_detail_shows_use_commands(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/chroots/work")
    assert response.status_code == 200
    assert "Use this chroot" in response.text
    assert "Copy shell command" in response.text



def test_api_retry_job_replays_install_with_overrides(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    web_app = client.app
    services = web_app.state.services
    jobs = web_app.state.jobs
    install_calls = []

    def fake_install(request, *, progress=None):
        install_calls.append(request)
        return {"ok": True}

    monkeypatch.setattr(services.install(), "install", fake_install)
    job = jobs.submit(
        kind="install",
        title="Install ubuntu (demo)",
        target_name="demo",
        log_path=None,
        retry={
            "action": "install.submit",
            "payload": {
                "distro": "ubuntu",
                "name": "demo",
                "username": "olduser",
                "mirror": "auto",
                "tools": [],
                "addons": [],
                "repair": False,
            },
            "label": "Retry install",
            "href": "/install?name=demo",
        },
        runner=lambda progress: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    client.get("/")
    csrf = client.cookies.get("chrootctl_csrf")
    result = client.post(f"/api/jobs/{job.job_id}/retry", json={"overrides": {"username": "newuser", "repair": True}}, headers={"x-csrf-token": csrf})
    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "queued"
    replay_job = jobs.get(data["job_id"], tail=0)
    assert replay_job.state == "succeeded"
    assert install_calls
    assert install_calls[0].username == "newuser"
    assert install_calls[0].repair is True


def test_repair_page_loads_with_plan_summary(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/repair")
    assert response.status_code == 200
    assert "Review and repair drift" in response.text
    assert "Plan summary" in response.text
    assert "Diff details" in response.text


def test_api_registry_repair_preview_selective(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.post(
        "/api/registry/repair/preview-selective",
        json={"decisions": [{"item_id": "chroot:orphan", "action": "register"}]},
        headers={"x-csrf-token": csrf_token(client)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["summary"]["selected_count"] == 1
    assert payload["selected"][0]["item_id"] == "chroot:orphan"


def test_api_latest_snapshot_recovery(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/api/chroots/work/recovery/latest-snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["snapshot"]["name"] == "snap-001"


def test_repair_page_renders_confirmation_modal(tmp_path: Path) -> None:
    client = TestClient(create_app(config_path=tmp_path / "config.toml", dry_run=True))
    response = client.get("/repair")
    assert response.status_code == 200
    assert 'id="repair-confirmation-dialog"' in response.text
    assert "Review repair plan before queueing" in response.text


def test_e2e_fixture_mode_seeds_failed_job(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHROOTCTL_E2E_FIXTURES", "1")
    app = create_app(config_path=tmp_path / "config.toml", dry_run=True)
    client = TestClient(app)
    response = client.get("/jobs/e2e-failed-install")
    assert response.status_code == 200
    assert "Fixture failed install" in response.text
    assert "Restore latest snapshot" in response.text


def test_e2e_fixture_chroot_detail_renders_snapshot_history(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROOTCTL_E2E_FIXTURES", "1")
    app = create_test_app(tmp_path)
    client = TestClient(app)
    response = client.get("/chroots/androidos")
    assert response.status_code == 200
    assert "snap-good-001" in response.text
    assert "Snapshots" in response.text


def test_transfer_page_includes_shared_confirmation(client):
    response = client.get("/transfer")
    assert response.status_code == 200
    body = response.text
    assert "global-confirmation-dialog" in body
    assert "Confirm chroot export" in body


def test_chroot_detail_includes_upgrade_confirmation(client):
    response = client.get("/chroots/androidos")
    assert response.status_code == 200
    body = response.text
    assert "Confirm chroot upgrade" in body
    assert "data-confirm-submit" in body
