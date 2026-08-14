from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_overlay10_support_is_managed_redacted_and_byte_bounded() -> None:
    support = text("src/chrootctl/services/support.py")
    bridge = text("src/chrootctl/bridge/registry.py")
    for token in ("managed_transfer_root", "require_contained", "_MAX_LOG_BYTES", "_MAX_JSON_BYTES", "_MAX_SUPPORT_UNCOMPRESSED_BYTES", "_PRIVATE_KEY_BLOCK", "_CLI_SECRET", "_URL_CREDENTIAL", "os.replace"):
        assert token in support
    assert 'extra_json={"debug/probes.json": probes, "debug/timeline.json": timeline}' in bridge
    assert 'create_root=False' in bridge
    assert "register_artifact" in bridge


def test_overlay10_readiness_rejects_stale_or_unbound_evidence() -> None:
    readiness = text("src/chrootctl/services/release_readiness.py")
    bridge = text("src/chrootctl/bridge/registry.py")
    docs = text("docs/release/VALIDATION_EVIDENCE.md")
    for token in ('"android_compileDebugKotlin"', '"android_testDebugUnitTest"', '"android_lintDebug"', '"module_zip"', '"source_no_webui"', '"sourceCommit"', '"compatibilityManifestSha256"', '_current_source_commit'):
        assert token in readiness
    assert '"ok": bool(evidence.get("ready"))' in bridge
    assert '"required": False' in bridge
    assert "source commit" in docs.lower()


def test_overlay10_repair_is_plan_only_transactional_and_symlink_safe() -> None:
    repair = text("src/chrootctl/services/repair.py")
    bridge = text("src/chrootctl/bridge/registry.py")
    assert "repair decision is stale or unknown" in repair
    assert "child.is_symlink()" in repair
    assert "apply_chroot_mutations" in repair
    assert "unbound registry repair is disabled" in repair
    assert "_strict_repair_decisions" in bridge
    assert '"repair.registry"' in bridge

def test_overlay10_final_preflight_uses_real_host_doctor_state() -> None:
    bridge = text("src/chrootctl/bridge/registry.py")
    assert 'runtime_status = "fail" if runtime_failures' in bridge
    assert '"Host doctor reports' in bridge
    assert '{"id": "runtime", "status": "pass", "detail": "Runtime query completed."}' not in bridge


def test_overlay10_smoke_and_diagnostic_operations_are_typed_and_managed() -> None:
    bridge = text("src/chrootctl/bridge/registry.py")
    for token in ('"smoke.run"', '"debug.export"', '"support.bundle"', '"system.module_build"', '"repair.apply"', 'register_artifact', 'managed_transfer'):
        assert token in bridge
    assert 'extra_json={"debug/probes.json": probes, "debug/timeline.json": timeline}' in bridge

