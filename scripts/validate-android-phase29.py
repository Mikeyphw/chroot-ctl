#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")

def main() -> int:
    errors: list[str] = []
    build = read("android/app/build.gradle.kts")
    registry = read("src/chrootctl/bridge/registry.py")
    transfer = read("src/chrootctl/services/transfer.py")
    lifecycle = read("src/chrootctl/services/lifecycle.py")
    service = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt")
    main_activity = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/MainActivity.kt")
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    strings = read("android/app/src/main/res/values/strings.xml")
    gitignore = read(".gitignore")
    docs = read("docs/android/PHASE_29_REAL_DEVICE_BUGFIX_SEAL.md")

    def err(condition: bool, message: str) -> None:
        if condition:
            errors.append(message)

    err('compileSdk = 36' not in build, "compileSdk must be 36")
    err('targetSdk = 36' not in build, "targetSdk must remain 36")
    err('versionName = "0.1.0-phase29"' not in build, "versionName must advance to phase29")

    for token in ("managed_transfer_root", "managed_transfer_archive", "artifact_root", "androidDescriptorRoot"):
        err(token not in transfer, f"transfer service missing managed-root token: {token}")
    err('tempfile.gettempdir()) / "chrootctl-transfer"' in registry, "registry must not create a separate transfer temp root")
    err('transfer.artifact_root' not in registry, "bridge registry missing transfer.artifact_root")
    err('query_handler=_transfer_artifact_root' not in registry, "transfer.artifact_root must be a query handler")
    err('payload.get("includeOptional") or payload.get("include_optional") or True' in registry, "smoke includeOptional=false must not be swallowed by or True")
    for token in ("_smoke_result_failed", "failCount", "resultPayload", "supportBundleRecommended"):
        err(token not in registry, f"smoke failure handoff missing token: {token}")

    err('resolved.path.startsWith(root.path)' in service, "root service must not use string-prefix path containment")
    for token in ("resolved.toPath().startsWith(root.toPath())", "resolved == root", "Only managed transfer artifacts"):
        err(token not in service, f"root service containment missing token: {token}")

    for token in ("TUS_VERSION", "tus_create_upload", "tus_status", "tus_patch", "/api/transfer/upload", "/api/transfer/tus"):
        err(token in transfer, f"retired browser upload/TUS fossil returned: {token}")
    for token in ("start_webui", "stop_webui", "restart_webui"):
        err(token in lifecycle, f"retired WebUI lifecycle helper returned: {token}")

    for token in ("RequestPermission", "Manifest.permission.POST_NOTIFICATIONS", "requestNotificationPermission"):
        err(token not in main_activity, f"notification permission request path missing token: {token}")
    for token in ("notifications_permission_title", "onRequestNotificationPermission"):
        err(token not in home and token not in app, f"notification UX wiring missing token: {token}")
    for token in ("notifications_permission_body", "notifications_permission_action"):
        err(token not in strings, f"notification string missing token: {token}")

    for token in (".devtool/state/", ".devtool/reports/", ".devtool/test-history.json"):
        err(token not in gitignore, f".gitignore missing devtool runtime state rule: {token}")
    # Devtool reserves .devtool/* as runtime metadata, so overlays must not target
    # those files directly. The project-side contract is to ignore them and keep
    # artifact inventories free of .devtool entries.

    kotlin = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"))
    for forbidden in ("WebView", "combine(arrayOf", '"/data/'):
        err(forbidden in kotlin, f"forbidden Android token found: {forbidden}")
    for token in ("Manifest.permission.POST_NOTIFICATIONS", "Build.VERSION.SDK_INT >= 33", "ContextCompat.checkSelfPermission", "ActivityResultContracts.RequestPermission"):
        err(token not in kotlin, f"notification permission flow missing guarded token: {token}")
    for token in ("Phase 29", "transfer.artifact_root", "includeOptional=false", "notification-permission"):
        err(token not in docs, f"phase29 docs missing token: {token}")

    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("Phase 29 real-device bugfix seal validator passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
