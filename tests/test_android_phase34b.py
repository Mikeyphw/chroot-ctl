from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def test_phase34b_bridge_drain_threads_catch_throwables() -> None:
    bridge = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    assert "catch (error: Throwable)" in bridge
    assert "uncaughtExceptionHandler = Thread.UncaughtExceptionHandler" in bridge
    assert "drainFailureMessage(name, error)" in bridge
    assert "closed without crashing the root service" in bridge
    assert bridge.count("drainFailureBuffer()") >= 2


def test_phase34b_drain_notes_go_to_error_output_not_stdout() -> None:
    bridge = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    assert "bridgeErrorOutput(stderr, drainFailures)" in bridge
    assert "output = stdout.asString()" in bridge
    assert "BoundedOutputStream(MAX_CAPTURE_BYTES)" in bridge
    assert "android-stream-drain" in bridge
    result_block = bridge.split("return BridgeProcessResult(", 1)[1].split("    }\n\n    fun stream", 1)[0]
    assert "errorOutput = bridgeErrorOutput(stderr, drainFailures)" in result_block
    assert "android-stream-drain" not in result_block.split("errorOutput", 1)[0]


def test_phase34b_log_signature_is_covered_by_hotfix() -> None:
    docs = read("docs/android/PHASE_34B_ROOTSERVICE_STREAM_CRASH_HOTFIX.md")
    bridge = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    assert "read interrupted by close() on another thread" in docs
    assert "BridgeProcess.drain" in docs
    assert "chrootctl-bridge-stdout" in bridge
    assert "chrootctl-bridge-stderr" in bridge


def test_phase34b_preserves_sdk_lint_and_trust_boundaries() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    aidl = read("android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl")
    kotlin = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt")
    )

    assert "compileSdk = 37" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    assert lint.count('<issue id="OldTargetApi" severity="ignore" />') == 1
    assert 'id="GradleDependency"' not in lint
    assert 'id="NewerVersionAvailable"' not in lint
    for forbidden_method in ("runShell(", "executeShell(", "command(String", "String shell("):
        assert forbidden_method not in aidl
    assert "WebView" not in kotlin
