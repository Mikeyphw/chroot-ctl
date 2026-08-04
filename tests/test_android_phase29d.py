from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def test_phase29d_runtime_resolver_probes_and_skips_stale_executables() -> None:
    resolver = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
    assert 'File(termuxHome, ".local/bin/chrootctl")' in resolver
    assert 'listOf("capabilities")' in resolver
    assert "selectCompatibleRuntime" in resolver
    assert "isCompatible" in resolver
    assert "cachedRuntime" in resolver


def test_phase29d_bridge_output_is_structured_before_protocol_parsing() -> None:
    process = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
    validator = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeOutputValidator.kt")
    service = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt")
    assert "redirectErrorStream(true)" not in process
    assert "errorOutput" in process
    assert "validateBridgeProcessResult" in service
    assert "INVALID_BRIDGE_RESPONSE" in validator
    assert "UNSUPPORTED_BRIDGE_PROTOCOL" in validator
    assert "RuntimeResolver.invalidate(runtime)" in service


def test_phase29d_protocol_shapes_are_strict_but_legacy_capabilities_are_supported() -> None:
    models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModels.kt")
    assert "operationsJson.getJSONObject" not in models
    assert "is String -> add(" in models
    assert "expected a JSON object" in models
    assert "expected a JSON array" in models
    assert "return data ?: JSONObject()" not in models
    assert "return dataArray ?: JSONArray()" not in models


def test_phase29d_initial_home_failure_is_visible_and_retryable() -> None:
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    assert "Loadable.Loading" in home
    assert "RefreshState.Failed" in home
    assert "InitialBackendFailure" in home
    assert "RecoverableErrorState" in home
    assert "action_retry" in home


def test_phase29d_action_groups_wrap_on_phone_widths() -> None:
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    install = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/install/InstallScreen.kt")
    tools = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    assert "ActionFlowRow" in home
    assert "FlowRow(" in install
    assert tools.count("FlowRow(") >= 10
    assert "smoke_report_action" in tools
    assert "smoke_export_action" in tools


def test_phase29d_sdk36_and_phase29c_lint_policy_are_preserved() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    assert "compileSdk = 36" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert '<issue id="OldTargetApi" severity="ignore" />' in lint
