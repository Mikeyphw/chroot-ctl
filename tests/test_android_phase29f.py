from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def test_phase29f_tracks_binder_death_and_releases_dead_binding() -> None:
    client = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt")
    assert "IBinder.DeathRecipient" in client
    assert "binder.linkToDeath(deathRecipient, 0)" in client
    assert "binder.unlinkToDeath" in client
    assert "override fun onBindingDied" in client
    assert "override fun onServiceDisconnected" in client
    assert client.count("RootService.unbind(connection)") >= 2
    assert "invalidateFromCallback" in client


def test_phase29f_probes_binder_before_dispatch_and_rebinds_stale_proxy() -> None:
    client = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt")
    assert "binder.isBinderAlive && binder.pingBinder()" in client
    assert "requireHealthyBinder(service.asBinder(), label)" in client
    assert "disconnectCurrent(\"Rebinding after an unavailable or stale privileged service connection\")" in client
    assert "bindMutex.withLock" in client
    assert "callMutex.withLock" in client


def test_phase29f_replays_only_read_only_calls_once() -> None:
    client = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt")
    recovery = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceRecovery.kt")

    for label in ("Service status", "Capabilities", "Query", "Preview", "Operation status"):
        assert f'call("{label}", BinderReplayPolicy.SAFE_READ_ONLY' in client
    for label in ("Cancel operation", "Import transfer", "Export transfer", "Start operation"):
        assert f'call("{label}", BinderReplayPolicy.NEVER' in client

    assert recovery.count("attempt()") == 2
    assert "if (replayPolicy == BinderReplayPolicy.NEVER)" in recovery
    assert "The request was not retried" in recovery
    assert "after reconnecting to the privileged service" in recovery


def test_phase29f_unit_contract_exercises_death_retry_and_no_replay() -> None:
    test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/root/RootServiceRecoveryTest.kt")
    assert "read only call reconnects and retries exactly once" in test
    assert "state changing call invalidates transport but is never replayed" in test
    assert "second transport failure is reported after one reconnect" in test
    assert "non transport failures are neither recovered nor replayed" in test
    assert "assertEquals(2, attempts)" in test
    assert "assertEquals(1, attempts)" in test


def test_phase29f_preserves_sdk36_lint_and_fixed_aidl_boundaries() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    client = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt")
    aidl = read("android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl")
    kotlin = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt")
    )

    assert "compileSdk = 37" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    assert '<issue id="OldTargetApi" severity="ignore" />' in lint
    assert "CATEGORY_DAEMON_MODE" not in client
    for forbidden_method in ("runShell(", "executeShell(", "command(String", "String shell("):
        assert forbidden_method not in aidl
    assert "WebView" not in kotlin
