#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise AssertionError(f"missing required file: {relative}")
    return path.read_text(encoding="utf-8", errors="strict")


def require(text: str, token: str, label: str) -> None:
    if token not in text:
        raise AssertionError(f"{label}: missing {token!r}")


def require_condition(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def forbid(text: str, token: str, label: str) -> None:
    if token in text:
        raise AssertionError(f"{label}: forbidden {token!r}")


def main() -> int:
    bridge = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    aidl = read("android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl")
    docs = read("docs/android/PHASE_34B_ROOTSERVICE_STREAM_CRASH_HOTFIX.md")
    test = read("tests/test_android_phase34b.py")

    for token in (
        "drainFailureBuffer",
        "bridgeErrorOutput(stderr, drainFailures)",
        "bridgeErrorOutput(stderr: ByteArrayOutputStream, drainFailures: List<String>)",
        "android-stream-drain",
        "catch (error: Throwable)",
        "uncaughtExceptionHandler = Thread.UncaughtExceptionHandler",
        "drainFailureMessage(name, error)",
        "closed without crashing the root service",
    ):
        require(bridge, token, "Bridge stream-drain crash guard")

    require_condition(bridge.count("drainFailureBuffer()") >= 2, "Bridge stream-drain crash guard must protect invoke and stream")
    require_condition(bridge.count("drain(") >= 4, "Bridge stream readers must use guarded drain helper")
    require_condition("output = String(stdout.toByteArray(), StandardCharsets.UTF_8)" in bridge, "stdout JSON must remain separate from drain notes")
    forbid(bridge, "source.copyTo(output, DEFAULT_BUFFER_SIZE) }\n    }, name)", "unguarded drain body")

    for token in (
        "read interrupted by close() on another thread",
        "BridgeProcess.drain",
        "background stream readers",
        "must not kill the libsu RootService process",
    ):
        require(docs, token, "Phase 34B documentation")

    for token in (
        "test_phase34b_bridge_drain_threads_catch_throwables",
        "test_phase34b_drain_notes_go_to_error_output_not_stdout",
        "test_phase34b_log_signature_is_covered_by_hotfix",
    ):
        require(test, token, "Phase 34B regression tests")

    require_condition("compileSdk = 36" in build and "targetSdk = 36" in build, "SDK 36 contract")
    require_condition("warningsAsErrors = true" in build and "abortOnError = true" in build, "strict lint contract")
    require_condition(re.findall(r'id="([^"]+)"', lint) == ["OldTargetApi"], "lint.xml must ignore only OldTargetApi")
    for forbidden_method in ("runShell(", "executeShell(", "command(String", "String shell("):
        forbid(aidl, forbidden_method, "fixed AIDL trust boundary")

    print("Phase 34B RootService stream crash hotfix validator passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"Phase 34B validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
