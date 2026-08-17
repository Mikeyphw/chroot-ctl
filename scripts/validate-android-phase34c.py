#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def main() -> int:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    docs = read("docs/android/PHASE_34C_ROOT_MODULE_RUNTIME_RESOLVER.md")
    tests = read("tests/test_android_phase34c.py")

    require("compileSdk = 37" in build, "compileSdk must be API 37")
    require("targetSdk = 36" in build, "targetSdk must remain API 36")
    require("warningsAsErrors = true" in build, "strict lint warningsAsErrors must remain enabled")
    require("abortOnError = true" in build, "strict lint abortOnError must remain enabled")
    ignored = re.findall(r'<issue\s+id="([^"]+)"\s+severity="ignore"\s*/>', lint)
    require(ignored == ["OldTargetApi"], f"only OldTargetApi may be ignored, got {ignored}")

    expected_in_order = [
        'File(activeModuleDir, "system/bin/chrootctl")',
        'File(File.separator, "system/bin/chrootctl")',
        'File(adbRoot, "chrootctl/bin/chrootctl")',
        'File(termuxHome, ".local/bin/chrootctl")',
        'File(termuxUsr, "bin/chrootctl")',
    ]
    positions = [resolver.find(token) for token in expected_in_order]
    for token, pos in zip(expected_in_order, positions):
        require(pos >= 0, f"runtime resolver missing candidate: {token}")
    require(positions == sorted(positions), "runtime resolver must prefer root-module paths before magic-mount, legacy, and Termux fallbacks")

    for token in (
        "rootModuleExecutableCandidates",
        "ksuRoot",
        "selectCompatibleRuntime(candidates, ::isCompatible)",
        'listOf("capabilities")',
        "data.optInt(\"protocolVersion\", -1) == BRIDGE_PROTOCOL_VERSION",
        "CHROOTCTL_EXECUTABLE",
    ):
        require(token in resolver, f"runtime resolver guard missing: {token}")

    require("File.separator" in resolver, "resolver must keep path construction portable and avoid hardcoded /data string literals")
    require('"/data/' not in resolver, "resolver Kotlin must not reintroduce forbidden quoted /data literals")
    require("pythonCandidates" in resolver, "Python bridge fallback must remain available")
    require("No active chrootctl executable or Python runtime was found" in resolver, "diagnostic must describe active-runtime discovery failure")

    for token in (
        "Phase 34C",
        "chrootctl-magisk",
        "/data/adb/modules/chrootctl-magisk/system/bin/chrootctl",
        "/system/bin/chrootctl",
        "Termux",
        "protocol-1",
        "API 36",
    ):
        require(token in docs, f"Phase 34C docs missing: {token}")

    active_candidates = re.search(
        r"private val rootModuleExecutableCandidates = listOf\((.*?)\n    \)",
        resolver,
        re.DOTALL,
    )
    require(active_candidates is not None, "runtime resolver must declare rootModuleExecutableCandidates")
    if active_candidates is not None:
        block = active_candidates.group(1)
        require("activeModuleDir" in block, "active module executable must remain a root-module candidate")
        require("modules_update" not in block, "pending module updates must never be executable candidates")
    require('File(adbRoot, "modules_update/chrootctl-magisk")' in resolver, "Magisk pending update must remain diagnostic")
    require('File(ksuRoot, "modules_update/chrootctl-magisk")' in resolver, "KernelSU pending update must remain diagnostic")
    require("pendingModuleDirs.filter(File::exists)" in resolver, "pending update diagnostics must remain visible")

    for token in (
        "test_phase34c_runtime_resolver_executes_active_module_only",
        "test_phase34c_invalid_override_falls_back_and_protocol_probe_is_required",
        "test_phase34c_lint_api36_and_active_only_docs_are_preserved",
    ):
        require(token in tests, f"Phase 34C tests missing contract: {token}")

    kotlin = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt")
    )
    for forbidden in ("WebView", "combine(arrayOf", '"/data/'):
        require(forbidden not in kotlin, f"forbidden Android regression returned: {forbidden}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 34C root-module runtime resolver validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
