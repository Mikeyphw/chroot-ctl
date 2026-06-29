from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from chrootctl.web.app import create_app

from tests.test_web_app import FakeJobs, FakeServices


def build_secured_client(tmp_path: Path, *, access_token: str | None = None) -> TestClient:
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
    app = create_app(config_path=config_path, dry_run=True, access_token=access_token)
    app.state.services = FakeServices()
    app.state.jobs = FakeJobs()
    return TestClient(app)


def _csrf_token(client: TestClient, path: str = "/") -> str:
    response = client.get(path)
    assert response.status_code == 200
    token = client.cookies.get("chrootctl_csrf")
    assert token
    return token


def test_post_routes_require_csrf_token(tmp_path: Path) -> None:
    client = build_secured_client(tmp_path)
    response = client.post("/chroots/work/start", follow_redirects=False)
    assert response.status_code == 403
    token = _csrf_token(client, "/chroots/work")
    allowed = client.post("/chroots/work/start", data={"csrf_token": token}, follow_redirects=False)
    assert allowed.status_code == 303


def test_access_token_protects_web_ui(tmp_path: Path) -> None:
    client = build_secured_client(tmp_path, access_token="secret-token")
    blocked = client.get("/")
    assert blocked.status_code == 401
    allowed = client.get("/", params={"access_token": "secret-token"})
    assert allowed.status_code == 200
    assert client.cookies.get("chrootctl_token") == "secret-token"
    again = client.get("/")
    assert again.status_code == 200


def test_destructive_and_sensitive_actions_require_explicit_confirmation(tmp_path: Path) -> None:
    client = build_secured_client(tmp_path)
    token = _csrf_token(client, "/chroots/work")
    rename = client.post(
        "/chroots/work/rename",
        data={"csrf_token": token, "new_name": "devbox", "confirm_name": "wrong"},
        follow_redirects=False,
    )
    assert rename.status_code == 400

    token = _csrf_token(client, "/chroots/work/users/mike")
    password = client.post(
        "/chroots/work/users/mike/password",
        data={
            "csrf_token": token,
            "password": "secret",
            "confirm_password": "secret",
            "confirm_username": "nope",
        },
        follow_redirects=False,
    )
    assert password.status_code == 400

    token = _csrf_token(client, "/install?distro=ubuntu")
    repair = client.post(
        "/install",
        data={
            "csrf_token": token,
            "distro": "ubuntu",
            "name": "work",
            "username": "mike",
            "repair": "true",
        },
        follow_redirects=False,
    )
    assert repair.status_code == 400
