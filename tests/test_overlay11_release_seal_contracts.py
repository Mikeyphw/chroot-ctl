from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _function_block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"def {name}")
    end = source.index(f"def {next_name}", start)
    return source[start:end]


def _load_recorder():
    path = ROOT / "scripts" / "record-validation-evidence.py"
    spec = importlib.util.spec_from_file_location("overlay11_recorder_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_final_seal():
    path = ROOT / "scripts" / "final-release-seal.py"
    spec = importlib.util.spec_from_file_location("overlay11_final_seal_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _complete_evidence_payload() -> dict[str, object]:
    check_ids = (
        "python_pytest", "python_mypy", "python_compileall", "android_contract_validators",
        "source_package", "android_compileDebugKotlin", "android_testDebugUnitTest",
        "android_lintDebug", "module_render", "module_zip", "module_shell", "source_no_webui",
    )
    checks = {
        check_id: {
            "status": "pass", "exitCode": 0, "command": "true", "provenance": "subprocess",
            "recordedAt": 2.0, "startedAt": 1.0, "finishedAt": 2.0,
        }
        for check_id in check_ids
    }
    return {
        "schemaVersion": 2, "generatedAt": 2.0, "validationStartedAt": 1.0, "validationCompletedAt": 2.0,
        "validationRunId": "run", "sourceCommit": "a" * 40, "sourceTree": "b" * 40,
        "validatedTree": "c" * 40, "compatibilityManifestSha256": "d" * 64, "checks": checks,
    }


def test_install_preview_resolves_arch_before_mirror_selection() -> None:
    source = _text("src/chrootctl/services/install.py")
    preview = _function_block(source, "preview_install", "preset_options")
    arch_assignment = 'arch = str(plan.get("arch") or request.arch)'
    mirror_call = "self.mirror_options(distro, arch)"
    assert arch_assignment in preview
    assert preview.index(arch_assignment) < preview.index(mirror_call)


def test_debug_registry_imports_os_for_runtime_probes() -> None:
    source = _text("src/chrootctl/bridge/registry.py")
    assert "import os" in source
    assert "os.access(" in source


def test_dry_run_install_phase_progress_is_ephemeral_and_step_journal_is_read_only() -> None:
    source = _text("src/chrootctl/base_install.py")
    current_phase = _function_block(source, "current_phase", "next_phase")
    mark_phase = _function_block(source, "mark_phase", "_chroot_shell")
    record_step = _function_block(source, "_record_install_step", "_run_tracked_phase")
    assert 'getattr(self, "_dry_run_phase", None)' in current_phase
    assert "self.runner.dry_run" in current_phase
    assert "if self.runner.dry_run:" in mark_phase
    assert "self._dry_run_phase = phase" in mark_phase
    assert "if self.runner.dry_run:" in record_step
    assert record_step.split("if self.runner.dry_run:", 1)[1].lstrip().startswith("return")


def test_pending_finalize_uid_sync_is_internal_and_narrowly_gated() -> None:
    sync = _text("src/chrootctl/user_sync.py")
    installer = _text("src/chrootctl/base_install.py")
    assert "allow_pending_finalize: bool = False" in sync
    assert 'phase == "desktop"' in sync
    assert '(self.config.chroot_base / "etc" / "passwd").is_file()' in sync
    assert "allow_pending_finalize=True" in installer


def test_direct_evidence_recorder_cannot_create_passing_evidence(tmp_path: Path) -> None:
    target = tmp_path / "forged.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/record-validation-evidence.py"), "--output", str(target)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
    )
    assert result.returncode != 0
    assert "refusing direct evidence recording" in result.stderr
    assert not target.exists()


def test_recorder_import_exposes_no_success_builder_or_writer_api() -> None:
    recorder = _load_recorder()
    for name in ("build_payload", "write_evidence", "_atomic_json_write", "validated_tree", "CHECK_IDS"):
        assert not hasattr(recorder, name), f"legacy recorder unexpectedly exposes forge-capable API: {name}"
    runner = _text("scripts/final-release-seal.py")
    assert "record-validation-evidence.py" in runner  # exact Overlay 11 tree inventory only
    assert "RECORDER" not in runner
    assert "build_payload(" not in runner
    assert "This is intentionally the only success-evidence assembly path" in runner


def test_evidence_reader_rejects_non_hex_git_ids_and_inexact_hash(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from chrootctl.services.release_readiness import ReleaseReadinessService
    payload = _complete_evidence_payload()
    payload["sourceCommit"] = "z" * 40
    path = tmp_path / "bad-oid.json"; path.write_text(json.dumps(payload)); path.chmod(0o600)
    _, problem = ReleaseReadinessService._read(path)
    assert "40-hex" in str(problem)
    payload = _complete_evidence_payload(); payload["compatibilityManifestSha256"] = "x" * 64
    path.write_text(json.dumps(payload)); path.chmod(0o600)
    _, problem = ReleaseReadinessService._read(path)
    assert "SHA-256" in str(problem)


def _identity_service(*, current: str, current_tree: str, parent: str, worktree: str, source_commit: str, source_tree: str):
    sys.path.insert(0, str(ROOT / "src"))
    from chrootctl.services.release_readiness import ReleaseReadinessService
    service = object.__new__(ReleaseReadinessService)
    service._current_source_commit = lambda: current
    service._current_source_tree = lambda: current_tree
    service._current_source_parent = lambda: parent
    service._current_worktree_tree = lambda: worktree
    service._tree_for_commit = lambda commit: source_tree if commit == source_commit else ""
    service._compatibility_manifest_hash = lambda: "d" * 64
    return service


def _identity_payload() -> dict[str, str]:
    return {
        "sourceCommit": "a" * 40,
        "sourceTree": "b" * 40,
        "validatedTree": "c" * 40,
        "compatibilityManifestSha256": "d" * 64,
    }


def test_release_readiness_accepts_exact_precommit_validated_worktree() -> None:
    payload = _identity_payload()
    service = _identity_service(
        current=payload["sourceCommit"], current_tree=payload["sourceTree"], parent="e" * 40,
        worktree=payload["validatedTree"], source_commit=payload["sourceCommit"], source_tree=payload["sourceTree"],
    )
    assert service._identity_problem(payload) is None


def test_release_readiness_rejects_rollback_stale_evidence_even_when_head_equals_source_commit() -> None:
    payload = _identity_payload()
    service = _identity_service(
        current=payload["sourceCommit"], current_tree=payload["sourceTree"], parent="e" * 40,
        worktree=payload["sourceTree"], source_commit=payload["sourceCommit"], source_tree=payload["sourceTree"],
    )
    assert "validatedTree" in str(service._identity_problem(payload))


def test_release_readiness_accepts_only_single_exact_devtool_commit_transition() -> None:
    payload = _identity_payload()
    final_commit = "f" * 40
    service = _identity_service(
        current=final_commit, current_tree=payload["validatedTree"], parent=payload["sourceCommit"],
        worktree=payload["validatedTree"], source_commit=payload["sourceCommit"], source_tree=payload["sourceTree"],
    )
    assert service._identity_problem(payload) is None
    service._current_source_parent = lambda: "9" * 40
    assert service._identity_problem(payload) is not None


def test_release_readiness_rejects_dirty_post_commit_worktree() -> None:
    payload = _identity_payload()
    service = _identity_service(
        current="f" * 40, current_tree=payload["validatedTree"], parent=payload["sourceCommit"],
        worktree="9" * 40, source_commit=payload["sourceCommit"], source_tree=payload["sourceTree"],
    )
    assert "exact current" in str(service._identity_problem(payload))


def test_release_readiness_fails_closed_when_compatibility_identity_cannot_be_verified() -> None:
    payload = _identity_payload()
    service = _identity_service(
        current="f" * 40, current_tree=payload["validatedTree"], parent=payload["sourceCommit"],
        worktree=payload["validatedTree"], source_commit=payload["sourceCommit"], source_tree=payload["sourceTree"],
    )
    service._compatibility_manifest_hash = lambda: ""
    assert "cannot be verified" in str(service._identity_problem(payload))


def test_evidence_reader_requires_schema_v2_and_private_mode(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from chrootctl.services.release_readiness import ReleaseReadinessService
    payload = _complete_evidence_payload()
    path = tmp_path / "evidence.json"; path.write_text(json.dumps(payload)); path.chmod(0o600)
    parsed, problem = ReleaseReadinessService._read(path)
    assert problem is None and parsed["schemaVersion"] == 2
    path.chmod(0o644)
    _, problem = ReleaseReadinessService._read(path)
    assert "permissions" in str(problem)



def test_evidence_writer_uses_mode_0600_and_refuses_symlink_ancestors(tmp_path: Path) -> None:
    final_seal = _load_final_seal()
    payload = _complete_evidence_payload()
    target = tmp_path / "state" / "validation-results.json"
    final_seal._atomic_json_write(target, payload)
    assert target.is_file() and not target.is_symlink()
    assert (target.stat().st_mode & 0o777) == 0o600

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink evidence path component"):
        final_seal._atomic_json_write(link / "new-child" / "validation-results.json", payload)
    assert not (real / "new-child").exists()


def test_transaction_tree_guard_calls_tree_builder_without_name_shadowing(monkeypatch) -> None:
    final_seal = _load_final_seal()
    source_commit = "a" * 40
    source_tree = "b" * 40
    expected_tree = "c" * 40

    def fake_git(*args: str, env=None) -> str:
        del env
        if args == ("rev-parse", "HEAD"):
            return source_commit
        if args == ("rev-parse", "HEAD^{tree}"):
            return source_tree
        raise AssertionError(f"unexpected git call: {args}")

    tree_builder_calls = 0

    def fake_validated_tree() -> str:
        nonlocal tree_builder_calls
        tree_builder_calls += 1
        return expected_tree

    monkeypatch.setattr(final_seal, "git", fake_git)
    monkeypatch.setattr(final_seal, "validated_tree", fake_validated_tree)
    monkeypatch.setattr(final_seal, "changed_paths", lambda: set(final_seal.EXPECTED_CHANGED_PATHS))

    final_seal.assert_transaction_tree(
        "runtime-shape",
        source_commit=source_commit,
        source_tree=source_tree,
        expected_validated_tree=expected_tree,
    )
    assert tree_builder_calls == 1



def test_final_seal_rejects_in_repo_validation_tmpdir_before_creation(monkeypatch) -> None:
    seal = _load_final_seal()
    forbidden = ROOT / ".devtool" / "overlay11-validation-env"
    assert not forbidden.exists()
    monkeypatch.setenv("DEVTOOL_VALIDATION_TMPDIR", str(forbidden))
    monkeypatch.delenv("TMPDIR", raising=False)
    with pytest.raises(RuntimeError, match="outside the Git checkout"):
        seal.validation_tmp_base()
    assert not forbidden.exists()


def test_final_seal_prepares_declared_dependency_complete_python_environment(tmp_path: Path, monkeypatch) -> None:
    final_seal = _load_final_seal()
    requirements = final_seal.declared_python_validation_requirements()
    joined = "\n".join(requirements).lower()
    for token in ("pydantic", "pytest", "mypy"):
        assert token in joined
    # Python 3.10 is still supported by pyproject.toml; the seal must not require tomllib.
    monkeypatch.setattr(final_seal, "tomllib", None)
    assert final_seal.declared_python_validation_requirements() == requirements

    calls: list[list[str]] = []
    guarded = False

    def fake_run(argv: list[str], *, cwd=final_seal.ROOT, env=None):
        del cwd, env
        calls.append(list(argv))
        if argv[:4] == [sys.executable, "-m", "venv", "--system-site-packages"]:
            venv_dir = Path(argv[4])
            python_path = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("", encoding="utf-8")
        return (1.0, 2.0)

    def fake_guard(*_args, **_kwargs):
        nonlocal guarded
        guarded = True

    monkeypatch.setattr(final_seal, "run", fake_run)
    monkeypatch.setattr(final_seal, "assert_transaction_tree", fake_guard)
    holder, python_executable, returned_requirements, gate_env = final_seal.prepare_python_validation_environment(
        tmp_path, parent_env={}, source_commit="a" * 40, source_tree="b" * 40, expected_validated_tree="c" * 40
    )
    try:
        assert guarded is True
        assert tuple(returned_requirements) == tuple(requirements)
        assert python_executable.parent.parent.is_relative_to(tmp_path)
        assert gate_env["PYTHONPATH"].startswith(str(final_seal.ROOT / "src"))
        assert calls[0][:4] == [sys.executable, "-m", "venv", "--system-site-packages"]
        assert calls[1][:4] == [str(python_executable), "-m", "pip", "install"]
        assert "pydantic>=2.7.0" in calls[1]
        assert "pytest>=8.0" in calls[1]
        assert "mypy>=1.10.0" in calls[1]
        assert calls[2][0:2] == [str(python_executable), "-c"]
    finally:
        holder.cleanup()


def test_final_seal_uses_validation_venv_interpreter_for_all_python_gates() -> None:
    runner = _text("scripts/final-release-seal.py")
    required = (
        'python_executable, env, source_commit=source_commit_id',
        '[str(python_executable), "-m", "mypy"',
        '[str(python_executable), "-m", "compileall"',
        '[str(python_executable), str(validator.relative_to(ROOT))]',
        '[str(python_executable), "manage_source.py"',
    )
    for token in required:
        assert token in runner
    assert '[sys.executable, "-m", "pytest"' not in runner


def test_final_seal_runs_each_gate_once_or_deduplicates_with_provenance() -> None:
    runner = _text("scripts/final-release-seal.py")
    for token in (
        'def run_pytest_gate', '"pytest", "-q", "-p", "no:cacheprovider"', 'partitioning lost or duplicated test files', 'def clear_python_test_caches',
        '"mypy", "--cache-dir"', '"compileall", "-q", "src"',
        'glob("validate-android-phase*.py")', '"build-source"', ':app:compileDebugKotlin',
        ':app:testDebugUnitTest', ':app:lintDebug', '"build-magisk"', '"bash", "-n", "build.sh"',
        'derivedFrom="android_contract_validators"', '_write_evidence(default_evidence_paths(), payload)',
    ):
        assert token in runner
    assert runner.count('if validator.name == "validate-android-phase20-21.py"') == 1
    assert '[sys.executable, "scripts/validate-android-phase20-21.py"]' not in runner
    assert 'devtool-manifest-task' not in runner
    assert 'Never trust an environment flag' in runner


def test_release_evidence_contract_binds_source_and_worktree_and_atomic_private_write() -> None:
    readiness = _text("src/chrootctl/services/release_readiness.py")
    docs = _text("docs/release/VALIDATION_EVIDENCE.md")
    recorder = _text("scripts/record-validation-evidence.py")
    final_seal = _text("scripts/final-release-seal.py")
    for token in ('payload.get("sourceTree")', 'payload.get("validatedTree")', '_current_worktree_tree', '_tree_for_commit'):
        assert token in readiness
    for token in ('"GIT_INDEX_FILE"', '"write-tree"', 'os.replace(temp, path)', 'os.fsync(handle.fileno())', '0o077'):
        assert token in final_seal or token in readiness
    assert "schemaVersion: 2" in docs
    assert "rollback" in docs.lower()
    assert "Calling it directly fails" in docs
    assert "hard-fail compatibility shim" in docs
    assert "devtool-manifest-task" not in recorder
    assert "devtool-manifest-task" not in readiness
    assert "build_payload" not in recorder
    assert "write_evidence" not in recorder


def test_malformed_bridge_request_is_rejected_before_service_initialization(monkeypatch) -> None:
    from chrootctl.bridge import cli as bridge_cli
    from chrootctl import services as services_module

    malformed = '{"protocolVersion":999,"requestId":"preflight","operation":"chroots.list","payload":{}}'
    monkeypatch.setattr(bridge_cli, "_read_request", lambda _path: malformed)

    initialized = False

    def forbidden_service_init(*_args, **_kwargs):
        nonlocal initialized
        initialized = True
        raise AssertionError("service container must not be created for malformed bridge input")

    monkeypatch.setattr(services_module, "create_service_container", forbidden_service_init)
    assert bridge_cli.main(["query", "--request-file", "-"]) == 2
    assert initialized is False




def test_android_lint_remediation_contract_is_strict_and_complete() -> None:
    versions = _text("android/gradle/libs.versions.toml")
    build = _text("android/app/build.gradle.kts")
    wrapper = _text("android/gradle/wrapper/gradle-wrapper.properties")
    lint = _text("android/app/lint.xml")
    strings = _text("android/app/src/main/res/values/strings.xml")
    chroots = _text("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    home = _text("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    service = _text("android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt")
    activity = _text("android/app/src/main/kotlin/com/mikeyphw/chrootctl/MainActivity.kt")

    assert "gradle-9.7.0-bin.zip" in wrapper
    assert "compileSdk = 37" in build and "targetSdk = 36" in build
    for token in (
        'kotlin = "2.4.10"', 'activity = "1.13.0"', 'compose = "1.12.0"',
        'material3 = "1.4.0"', 'core = "1.19.0"', 'lifecycle = "2.11.0"',
        'room = "2.8.4"', 'coroutines = "1.11.0"', 'json = "20260719"',
    ):
        assert token in versions
    assert '<issue id="OldTargetApi" severity="ignore" />' in lint
    for forbidden in ("GradleDependency", "NewerVersionAvailable", "AndroidGradlePluginVersion", "UnusedResources", "PluralsCandidate", "UseKtx"):
        assert forbidden not in lint

    stale_resources = (
        "status_backend_unavailable", "metric_chroots", "metric_chroots_detail", "metric_operations",
        "metric_operations_detail", "refresh_failed_title", "chroot_unknown_distribution", "chroot_health_line",
        "tools_empty_body", "chroot_detail_title", "chroot_detail_body", "install_native_title",
        "install_native_body", "install_request_title", "install_form_profiles", "snapshot_actions_title",
        "action_preview_restore_snapshot", "action_preview_export_snapshot", "users_actions_title",
        "services_actions_title", "action_preview_short", "catalog_title", "package_title", "transfer_title",
        "transfer_saf_body", "transfer_pick_import_action", "transfer_import_name_label", "transfer_export_name_label",
        "artifacts_refresh_action", "artifacts_cleanup_action", "artifact_row", "system_support_title",
        "repair_preview_action", "repair_apply_action", "debug_workbench_title", "debug_workbench_body",
        "debug_run_probes_action", "debug_probes_title", "debug_no_probes", "smoke_handoff_title",
        "smoke_handoff_body", "nav_help", "glyph_help", "operation_latest_snapshot_line",
        "operation_restore_confirmation_label", "operation_restore_latest_action", "help_open_activity_action",
        "logs_target_label", "logs_level_all", "logs_source_line", "destination_help_subtitle",
        "chroots_phase32_title", "action_open_details", "install_ready_to_preview", "phase34_release_seal_title",
        "phase34_release_seal_body", "phase34_accessibility_summary",
    )
    for name in stale_resources:
        assert f'name="{name}"' not in strings

    for name in (
        "action_show_system_users", "metric_running_chroots_detail", "metric_active_operations_detail",
        "home_health_ready_count", "home_health_chroots_detail", "home_health_operations_detail",
        "chroot_warnings_count", "chroot_workspace_checks_more",
    ):
        assert f'<plurals name="{name}">' in strings
    assert "R.plurals.action_show_system_users" in chroots
    assert "R.plurals.chroot_warnings_count" in chroots
    assert "R.plurals.chroot_workspace_checks_more" in chroots
    for name in ("metric_running_chroots_detail", "metric_active_operations_detail", "home_health_ready_count", "home_health_chroots_detail", "home_health_operations_detail"):
        assert f"R.plurals.{name}" in home
    assert "%3$d B" in strings

    assert "import androidx.core.content.edit" in service
    assert ".edit()." not in service
    assert "mutableLongStateOf(0L)" in activity

    contract_text = "\n".join(
        p.read_text(encoding="utf-8")
        for folder in (ROOT / "scripts", ROOT / "tests")
        for p in folder.glob("*.py")
        if p != Path(__file__)
    )
    assert "compileSdk = 36" not in contract_text

def test_final_seal_has_no_android_prevalidated_bypass() -> None:
    runner = (ROOT / "scripts/final-release-seal.py").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts/validate-final-release-seal.sh").read_text(encoding="utf-8")
    assert "--devtool-android-prevalidated" not in runner
    assert "CHROOTCTL_DEVTOOL_ANDROID_TASKS" not in runner
    assert "devtool-manifest-task" not in runner
    assert '["./gradlew", *ANDROID_TASKS]' in runner
    assert "--devtool-android-prevalidated" not in wrapper
