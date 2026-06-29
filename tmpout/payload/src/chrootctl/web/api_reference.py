
from __future__ import annotations

from typing import Any


def api_reference_sections() -> list[dict[str, Any]]:
    return [
        {
            "title": "Install and preview",
            "items": [
                {"method": "GET", "path": "/api/install/options", "summary": "Resolved wizard defaults, compatibility rules, mirrors, presets, and known users.", "example": None},
                {"method": "POST", "path": "/api/install/validate", "summary": "Validate an install request and return blocking issues or a resolved plan.", "example": {"distro": "ubuntu", "name": "work", "username": "alice", "preset": "minimal-server", "profile": "minimal", "desktop": "none"}},
                {"method": "POST", "path": "/api/install/preview", "summary": "Dry-run install preview with storage estimates, mirror chain, and warnings.", "example": {"distro": "ubuntu", "name": "work", "username": "alice", "profile": "minimal", "desktop": "none"}},
                {"method": "GET", "path": "/api/install/preview/upgrade?name=work", "summary": "Preview upgrade readiness and dry-run command for an installed chroot.", "example": None},
            ],
        },
        {
            "title": "Transfer and archives",
            "items": [
                {"method": "GET", "path": "/api/transfer/readiness", "summary": "Cross-arch readiness and emulation advisories for transfer/import flows.", "example": None},
                {"method": "GET", "path": "/api/transfer/inspect?archive=/data/local/tmp/work.tar.zst", "summary": "Inspect archive metadata, checksum state, and suggested import name.", "example": None},
                {"method": "GET", "path": "/api/transfer/preview/export?name=work", "summary": "Preview export output path, checksum companion file, and space needs.", "example": None},
                {"method": "GET", "path": "/api/transfer/preview/import?archive=/data/local/tmp/work.tar.zst&conflict=rename", "summary": "Preview import decisions before queueing, including conflict mode.", "example": None},
                {"method": "GET", "path": "/api/transfer/temp", "summary": "List cached temporary archives, total bytes, and quick cleanup actions.", "example": None},
                {"method": "POST", "path": "/api/transfer/upload/init", "summary": "Start a resumable upload session for a local archive file.", "example": {"filename": "androidos.tar.zst", "total_size": 104857600, "content_type": "application/zstd"}},
                {"method": "PUT", "path": "/api/transfer/upload/{session_id}/chunk?offset=0", "summary": "Append a raw binary chunk to an existing resumable upload session.", "example": None},
                {"method": "GET", "path": "/api/transfer/upload/{session_id}", "summary": "Read resumable upload session status, current offset, and final file targets.", "example": None},
                {"method": "POST", "path": "/api/transfer/upload/{session_id}/complete", "summary": "Finalize a resumable upload session and emit a checksum sidecar file.", "example": {"expected_size": 104857600}},
                {"method": "DELETE", "path": "/api/transfer/upload/{session_id}", "summary": "Abort a resumable upload session and remove any partial file data.", "example": None},
            ],
        },
        {
            "title": "Jobs, repair, and recovery",
            "items": [
                {"method": "GET", "path": "/api/jobs", "summary": "List queued, running, and terminal jobs with lightweight summaries.", "example": None},
                {"method": "GET", "path": "/api/jobs/{job_id}", "summary": "Detailed job state, progress, retry metadata, latest log tail, and structured errors.", "example": None},
                {"method": "POST", "path": "/api/jobs/{job_id}/retry", "summary": "Replay a retry-capable job with optional override payload.", "example": {"overrides": {"username": "mike", "mirror": "kernel"}}},
                {"method": "GET", "path": "/api/registry/repair/preview-detailed", "summary": "Full registry drift preview with per-item actions and impact details.", "example": None},
                {"method": "POST", "path": "/api/registry/repair/preview-selective", "summary": "Dry-run a selective repair plan before queueing the real repair job.", "example": {"item_ids": ["chroot:androidos"], "actions": {"chroot:androidos": "fix-path"}}},
                {"method": "POST", "path": "/api/chroots/androidos/recovery/latest-snapshot", "summary": "Queue latest-snapshot recovery for a target chroot.", "example": None},
            ],
        },
        {
            "title": "Doctor, logs, support",
            "items": [
                {"method": "GET", "path": "/api/doctor/host", "summary": "Host readiness: root, tools, writable paths, qemu/binfmt, network, and blockers.", "example": None},
                {"method": "GET", "path": "/api/logs/unified?tail=100", "summary": "Unified log tail with level/search filtering data for the web log viewer.", "example": None},
                {"method": "GET", "path": "/api/events?limit=20", "summary": "Recent audit/support events for installs, repairs, builds, and transfers.", "example": None},
                {"method": "POST", "path": "/api/support-bundle", "summary": "Create a sanitized support bundle with logs, doctor output, config, and job summaries.", "example": {"include_logs": True}},
            ],
        },
    ]
