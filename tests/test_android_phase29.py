from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def test_phase29_transfer_root_is_shared_and_reported() -> None:
    transfer = read("src/chrootctl/services/transfer.py")
    registry = read("src/chrootctl/bridge/registry.py")
    assert "managed_transfer_root" in transfer
    assert "androidDescriptorRoot" in transfer
    assert "managed_transfer_archive" in transfer
    assert "transfer.artifact_root" in registry
    assert "query_handler=_transfer_artifact_root" in registry
    assert 'tempfile.gettempdir()) / "chrootctl-transfer"' not in registry


def test_phase29_transfer_descriptor_containment_is_canonical() -> None:
    service = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt")
    assert "resolved.toPath().startsWith(root.toPath())" in service
    assert "resolved == root" in service
    assert "resolved.path.startsWith(root.path)" not in service


def test_phase29_smoke_handoff_detects_failed_result_payload() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    assert "_smoke_result_failed" in registry
    assert "resultPayload" in registry
    assert "failCount" in registry
    assert 'optional_bool(payload, "includeOptional", "include_optional", default=True' in registry
    assert 'payload.get("includeOptional") or payload.get("include_optional") or True' not in registry


def test_phase29_browser_upload_and_webui_fossils_removed() -> None:
    transfer = read("src/chrootctl/services/transfer.py")
    lifecycle = read("src/chrootctl/services/lifecycle.py")
    for token in ("TUS_VERSION", "tus_create_upload", "tus_status", "tus_patch", "/api/transfer/upload", "/api/transfer/tus"):
        assert token not in transfer
    for token in ("start_webui", "stop_webui", "restart_webui"):
        assert token not in lifecycle


def test_phase29_notification_permission_ux_and_state_hygiene() -> None:
    main = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/MainActivity.kt")
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    strings = read("android/app/src/main/res/values/strings.xml")
    gitignore = read(".gitignore")
    assert "RequestPermission" in main
    assert "Manifest.permission.POST_NOTIFICATIONS" in main
    assert "notifications_permission_title" in home
    assert "notifications_permission_body" in strings
    for token in (".devtool/state/", ".devtool/reports/", ".devtool/test-history.json"):
        assert token in gitignore
    # .devtool/* is Devtool-owned runtime metadata. The overlay must ignore it
    # instead of trying to delete reserved metadata entries.


def test_phase29_android_guardrails_remain_clean() -> None:
    kotlin = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"))
    assert "WebView" not in kotlin
    assert "Manifest.permission.POST_NOTIFICATIONS" in kotlin
    assert "Build.VERSION.SDK_INT >= 33" in kotlin
    assert "ActivityResultContracts.RequestPermission" in kotlin
    assert "combine(arrayOf" not in kotlin
    assert '"/data/' not in kotlin
    build = read("android/app/build.gradle.kts")
    assert 'compileSdk = 37' in build
    assert 'targetSdk = 36' in build
    assert 'versionName = "0.1.0-phase29"' in build
