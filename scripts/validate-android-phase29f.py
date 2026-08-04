#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise AssertionError(f"missing required file: {relative}")
    return path.read_text(encoding="utf-8", errors="strict")


def require(text: str, token: str, label: str) -> None:
    if token not in text:
        raise AssertionError(f"{label}: missing {token!r}")


def forbid(text: str, token: str, label: str) -> None:
    if token in text:
        raise AssertionError(f"{label}: forbidden {token!r}")


def require_method_policy(client: str, signature: str, label: str, policy: str) -> None:
    pattern = re.compile(
        rf"suspend fun {re.escape(signature)}.*?=\s*(?:\n\s*)?call\(\"{re.escape(label)}\",\s*BinderReplayPolicy\.{policy}",
        re.DOTALL,
    )
    if not pattern.search(client):
        raise AssertionError(f"replay policy: {signature} must use {policy}")


def main() -> int:
    client = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt")
    recovery = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceRecovery.kt")
    unit_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/root/RootServiceRecoveryTest.kt")
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    aidl = read("android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl")
    docs = read("docs/android/PHASE_29F_BINDER_DEATH_RECOVERY.md")

    for token in (
        "IBinder.DeathRecipient",
        "binder.linkToDeath(deathRecipient, 0)",
        "binder.unlinkToDeath",
        "binder.isBinderAlive && binder.pingBinder()",
        "override fun onBindingDied",
        "override fun onServiceDisconnected",
        "RootService.unbind(connection)",
        "disconnectCurrent(transportReason(label, error))",
        "The privileged service process died",
    ):
        require(client, token, "Binder lifecycle recovery")

    if client.count("RootService.unbind(connection)") < 2:
        raise AssertionError("Binder lifecycle recovery: both synchronous reset and callback cleanup must unbind")
    if client.count("binder.unlinkToDeath") < 2:
        raise AssertionError("Binder lifecycle recovery: stale and active death recipients must be unlinked")

    require(client, "withContext(Dispatchers.Main.immediate)", "libsu main-thread binding")
    require(client, "withContext(Dispatchers.IO) { block(service) }", "off-main AIDL transaction")
    require(client, "callMutex.withLock", "serialized AIDL dispatch")
    require(client, "bindMutex.withLock", "serialized root-service binding")
    require(client, "postUnbind", "callback-safe unbinding")

    require_method_policy(client, "serviceInfo(): String", "Service status", "SAFE_READ_ONLY")
    require_method_policy(client, "capabilities(): String", "Capabilities", "SAFE_READ_ONLY")
    require_method_policy(client, "query(requestJson: String): String", "Query", "SAFE_READ_ONLY")
    require_method_policy(client, "preview(requestJson: String): String", "Preview", "SAFE_READ_ONLY")
    require_method_policy(client, "operationState(operationId: String): String", "Operation status", "SAFE_READ_ONLY")
    require_method_policy(client, "cancelOperation(operationId: String): String", "Cancel operation", "NEVER")
    require(client, 'call("Import transfer", BinderReplayPolicy.NEVER', "import replay guard")
    require(client, 'call("Export transfer", BinderReplayPolicy.NEVER', "export replay guard")
    require(client, 'call("Start operation", BinderReplayPolicy.NEVER', "operation-start replay guard")

    for token in (
        "RootServiceTransportException",
        "enum class BinderReplayPolicy",
        "SAFE_READ_ONLY",
        "NEVER",
        "recover(firstFailure)",
        "if (replayPolicy == BinderReplayPolicy.NEVER)",
        "The request was not retried",
        "after reconnecting to the privileged service",
    ):
        require(recovery, token, "recovery policy")
    if recovery.count("attempt()") != 2:
        raise AssertionError("recovery policy must contain exactly the initial attempt and one retry")

    for token in (
        "read only call reconnects and retries exactly once",
        "state changing call invalidates transport but is never replayed",
        "second transport failure is reported after one reconnect",
        "non transport failures are neither recovered nor replayed",
        "assertEquals(2, attempts)",
        "assertEquals(1, attempts)",
    ):
        require(unit_test, token, "Binder recovery unit tests")

    require(build, "compileSdk = 36", "SDK contract")
    require(build, "targetSdk = 36", "SDK contract")
    require(build, "warningsAsErrors = true", "lint contract")
    require(build, "abortOnError = true", "lint contract")
    require(lint, '<issue id="OldTargetApi" severity="ignore" />', "Phase 29C lint policy")

    forbid(client, "CATEGORY_DAEMON_MODE", "root-service lifecycle")
    for forbidden_method in ("runShell(", "executeShell(", "command(String", "String shell("):
        forbid(aidl, forbidden_method, "fixed AIDL trust boundary")
    forbid(client, "repeat(", "unbounded transport retries")
    forbid(client, "while (true) {\n            call", "unbounded transport retries")

    for token in (
        "Phase 29F",
        "linkToDeath",
        "pingBinder",
        "Retry a read-only request at most once",
        "Never replay operation start",
        "compileSdk = 36",
        "targetSdk = 36",
        "Daemon mode is intentionally not enabled",
    ):
        require(docs, token, "Phase 29F documentation")

    print("Phase 29F Binder death recovery validator passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"Phase 29F validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
