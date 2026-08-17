from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_phase32_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate-android-phase32.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

def test_chroots_screen_uses_search_filters_and_wrapping_actions() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    assert "chroots_search_label" in source
    assert "ChrootFilterButton" in source
    assert "Phase32ChrootCard" in source
    assert "ActionFlowRow" in source
    assert "Row(horizontalArrangement = Arrangement.spacedBy(8.dp))" not in source

def test_compact_chroot_cards_expose_promised_contextual_actions() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    if "ChrootWorkspaceScreen" in source:
        compact_card = source.split("private fun Phase32ChrootCard", 1)[1].split("private fun ChrootWorkspaceScreen", 1)[0]
        assert 'onPreviewLifecycle(chroot.name, "start")' in compact_card
        assert 'onPreviewLifecycle(chroot.name, "restart")' in compact_card
        assert 'onPreviewSnapshotCreate(chroot.name)' in compact_card
        assert "action_open_workspace" in compact_card
        assert "UsersPanel(" not in compact_card
        assert "ServicesPanel(" not in compact_card
    else:
        compact_card = source.split("private fun Phase32ChrootCard", 1)[1].split("private fun ChrootDetailCard", 1)[0]
        assert 'onPreviewLifecycle(chroot.name, "start")' in compact_card
        assert 'onPreviewLifecycle(chroot.name, "restart")' in compact_card
        assert 'onPreviewSnapshotCreate(chroot.name)' in compact_card
        assert 'onPreviewLifecycle(chroot.name, "upgrade")' in compact_card
        assert 'onPreviewLifecycle(chroot.name, "upgrade")' in compact_card
        assert 'onPreviewLifecycle(chroot.name, "remove")' in compact_card
        assert "action_open_workspace" in compact_card

def test_install_screen_is_a_three_step_preview_first_wizard() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/install/InstallScreen.kt")
    for token in ("InstallWizardStep", "ChooseSystem", "Configure", "Review", "PreviewCard", "onStartInstall"):
        assert token in source
    assert "onOpenActivity" in source
    assert "isError = !valid" in source
    assert "install_distro_error" in source
    assert "InstallWizardStep.Configure -> validation.valid" in source
    assert "if (step != InstallWizardStep.Review)" in source

def test_upgrade_operation_is_preview_first_registered_and_not_dead_ended() -> None:
    registry = read("src/chrootctl/bridge/registry.py")
    preview = read("src/chrootctl/services/preview.py")
    assert "def _upgrade_chroot" in registry
    assert 'OperationSpec("chroots.upgrade"' in registry
    section = registry.split("def _upgrade_chroot", 1)[1].split("def _remove_chroot", 1)[0]
    assert "services.preview().upgrade" in section
    assert "services.install().upgrade" in section
    assert "cancelled()" in section
    assert 'preview_ok = bool(preview.get("ok", len(blocking) == 0))' in section
    upgrade_preview = preview.split("def upgrade", 1)[1].split("def", 1)[0]
    assert '"ok": ok' in upgrade_preview
    assert '"message": "Upgrade preview is ready." if ok else "Upgrade preview has blocking issues."' in upgrade_preview

def test_sdk_lint_and_trust_boundaries_are_preserved() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    kotlin = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "android/app/src/main/kotlin").rglob("*.kt"))
    assert "compileSdk = 37" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    assert 'id="OldTargetApi" severity="ignore"' in lint
    assert 'id="WarningsAsErrors" severity="ignore"' not in lint
    assert 'id="ObsoleteLintCustomCheck" severity="ignore"' not in lint
    assert "WebView" not in kotlin
    assert "Runtime.getRuntime().exec" not in kotlin
