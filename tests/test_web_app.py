from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from chrootctl.base_install import ReleaseRef
from chrootctl.catalog import ManifestEntry
from chrootctl.chroot_users import ChrootUser
from chrootctl.models import (
    CatalogApplyResult,
    CheckRow,
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
        return InstallWizardDefaults(distro=distro or "ubuntu", name=name or "work", username="mike", profile="dev")

    def distros(self):
        return ("ubuntu", "arch")

    def profiles(self):
        return ("minimal", "dev")

    def desktops(self):
        return ("auto", "none")

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


class FakeServices:
    def system(self):
        return FakeSystemService()

    def chroots(self):
        return FakeChrootService()

    def users(self, *, name: str | None = None):
        return FakeUserService()

    def catalog(self, kind: str, *, name: str | None = None):
        return FakeCatalogService(kind)

    def install(self):
        return FakeInstallService()


class FakeJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, JobSnapshot] = {}
        self.counter = 0

    def submit(self, *, kind: str, title: str, runner, target_name: str | None = None, log_path=None):
        self.counter += 1
        job_id = str(self.counter)
        holder = {"text": "Queued"}

        def progress(text: str) -> None:
            holder["text"] = text

        result = runner(progress)
        snapshot = JobSnapshot(
            job_id=job_id,
            kind=kind,
            title=title,
            state="succeeded",
            progress_text=holder["text"],
            created_at=0.0,
            started_at=0.0,
            finished_at=1.0,
            target_name=target_name,
            log_path=log_path,
            result_payload=result,
            next_steps=tuple(getattr(result, "next_steps", ())),
            log_lines=("line one", "line two"),
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


def build_client(tmp_path: Path) -> TestClient:
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
    return TestClient(app)



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


def test_dashboard_route_renders(tmp_path: Path) -> None:
    client = build_client(tmp_path)
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

    events = client.get("/api/logs/events", params={"name": "work", "level": "error", "follow": "false"})
    assert events.status_code == 200
    assert '"snapshot"' in events.text
    assert '"ERROR"' in events.text
    assert '"/tmp/chrootctl.log"' in events.text

def test_install_submit_queues_job_and_job_page_renders(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    page = client.get("/install", params={"distro": "ubuntu"})
    assert page.status_code == 200
    assert "Install Wizard" in page.text
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
