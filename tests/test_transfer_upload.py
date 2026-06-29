
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chrootctl.errors import AppError
from chrootctl.services.transfer import TransferService
from chrootctl.web.app import create_app


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict[str, object]]] = []

    def record(self, event: str, *, target: str, message: str, metadata: dict[str, object] | None = None) -> None:
        self.events.append((event, target, message, metadata or {}))


class FakeServices:
    def __init__(self) -> None:
        self._audit = FakeAudit()

    def audit(self) -> FakeAudit:
        return self._audit

    def preview(self):
        raise AssertionError("preview should not be used in upload lifecycle test")

    def chroots(self):
        raise AssertionError("chroots should not be used in upload lifecycle test")


def test_transfer_service_upload_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chrootctl.services.transfer._transfer_temp_dir", lambda: tmp_path)
    service = TransferService(FakeServices())

    started = service.start_upload(filename="androidos.tar.zst", total_size=6, content_type="application/zstd")
    session_id = started["session_id"]

    status = service.upload_status(session_id)
    assert status["received_bytes"] == 0
    assert status["resumable"] is True

    after_first = service.upload_chunk(session_id=session_id, offset=0, data=b"abc")
    assert after_first["received_bytes"] == 3

    with pytest.raises(AppError):
        service.upload_chunk(session_id=session_id, offset=0, data=b"x")

    after_second = service.upload_chunk(session_id=session_id, offset=3, data=b"def")
    assert after_second["received_bytes"] == 6

    completed = service.complete_upload(session_id=session_id, expected_size=6)
    assert completed["complete"] is True
    assert completed["resumable"] is False
    assert Path(completed["final_path"]).exists()
    assert Path(completed["checksum_path"]).exists()

    with pytest.raises(AppError):
        service.upload_chunk(session_id=session_id, offset=6, data=b"!")

    aborted = service.abort_upload(session_id=session_id)
    assert aborted["aborted"] is True
    assert not Path(completed["final_path"]).exists()


def test_transfer_upload_api_lifecycle() -> None:
    app = create_app()
    client = TestClient(app)

    client.get("/docs")
    csrf_token = client.cookies.get("chrootctl_csrf", "")

    started = client.post(
        "/api/transfer/upload/init",
        json={"filename": "seeded.tar.zst", "total_size": 6, "content_type": "application/zstd"},
        headers={"x-csrf-token": csrf_token},
    )
    assert started.status_code == 200, started.text
    session = started.json()
    session_id = session["session_id"]

    status = client.get(f"/api/transfer/upload/{session_id}")
    assert status.status_code == 200, status.text
    assert status.json()["received_bytes"] == 0

    chunk = client.put(
        f"/api/transfer/upload/{session_id}/chunk",
        params={"offset": 0},
        content=b"abc",
        headers={"content-type": "application/octet-stream", "x-csrf-token": csrf_token},
    )
    assert chunk.status_code == 200, chunk.text
    assert chunk.json()["received_bytes"] == 3

    conflict = client.put(
        f"/api/transfer/upload/{session_id}/chunk",
        params={"offset": 0},
        content=b"z",
        headers={"content-type": "application/octet-stream", "x-csrf-token": csrf_token},
    )
    assert conflict.status_code == 409, conflict.text

    chunk2 = client.put(
        f"/api/transfer/upload/{session_id}/chunk",
        params={"offset": 3},
        content=b"def",
        headers={"content-type": "application/octet-stream", "x-csrf-token": csrf_token},
    )
    assert chunk2.status_code == 200, chunk2.text

    completed = client.post(f"/api/transfer/upload/{session_id}/complete", json={"expected_size": 6}, headers={"x-csrf-token": csrf_token})
    assert completed.status_code == 200, completed.text
    payload = completed.json()
    assert payload["complete"] is True
    assert payload["resumable"] is False

    aborted = client.delete(f"/api/transfer/upload/{session_id}", headers={"x-csrf-token": csrf_token})
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["aborted"] is True


def test_api_docs_page_mentions_resumable_upload_abort() -> None:
    app = create_app()
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 200, response.text
    assert "/api/transfer/upload/{session_id}" in response.text
    assert "Abort a resumable upload session" in response.text

def test_tus_upload_api_lifecycle() -> None:
    app = create_app()
    client = TestClient(app)

    client.get("/docs")
    csrf_token = client.cookies.get("chrootctl_csrf", "")

    options = client.options("/api/transfer/tus/files")
    assert options.status_code == 204
    assert options.headers["Tus-Resumable"] == "1.0.0"

    create = client.post(
        "/api/transfer/tus/files",
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Length": "6",
            "Upload-Metadata": "filename c2VlZGVkLnRhci56c3Q=",
            "x-csrf-token": csrf_token,
        },
    )
    assert create.status_code == 200, create.text
    session_id = create.json()["session_id"]

    head = client.head(f"/api/transfer/tus/files/{session_id}")
    assert head.status_code == 204, head.text
    assert head.headers["Upload-Offset"] == "0"

    patch1 = client.patch(
        f"/api/transfer/tus/files/{session_id}",
        content=b"abc",
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
            "x-csrf-token": csrf_token,
        },
    )
    assert patch1.status_code == 200, patch1.text
    assert patch1.json()["upload_offset"] == 3

    patch2 = client.patch(
        f"/api/transfer/tus/files/{session_id}",
        content=b"def",
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "3",
            "Content-Type": "application/offset+octet-stream",
            "x-csrf-token": csrf_token,
        },
    )
    assert patch2.status_code == 200, patch2.text
    assert patch2.json()["complete"] is True
    assert patch2.json()["upload_offset"] == 6

    delete = client.delete(f"/api/transfer/tus/files/{session_id}", headers={"x-csrf-token": csrf_token})
    assert delete.status_code == 200, delete.text
    assert delete.json()["aborted"] is True
