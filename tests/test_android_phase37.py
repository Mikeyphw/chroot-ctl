from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_phase37_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate-android-phase37.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

def test_services_workspace_is_focused_and_filterable() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    services = source.split("private fun ServicesPanel", 1)[1].split("private fun userPayload", 1)[0]
    assert "enum class ServiceWorkspaceFilter" in policy
    assert "serviceWorkspaceFilters().forEach" in services
    assert "FocusedServiceRow" in services
    assert "ServiceActionReviewSheet" in services
    assert "serviceMatchesWorkspaceFilter" in services

def test_service_rows_do_not_duplicate_preview_buttons() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    services = source.split("private fun ServicesPanel", 1)[1].split("private fun userPayload", 1)[0]
    focused_row = services.split("private fun FocusedServiceRow", 1)[1].split("private fun ServiceActionReviewSheet", 1)[0]
    assert "action_preview_short" not in services
    assert "private fun ServiceActionButton" not in services
    assert "onPreviewServicePayload" not in focused_row
    assert "onStartServiceOperation" not in focused_row
    assert "onSelectServiceAction(service" in focused_row

def test_service_action_review_sheet_owns_preview_and_execution() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    review = source.split("private fun ServiceActionReviewSheet", 1)[1].split("private fun serviceActionLabel", 1)[0]
    assert "action_preview_command" in review
    assert "onPreviewServicePayload(payload)" in review
    assert "onStartServiceOperation(operation, payload)" in review
    assert "service_action_review_title" in review
    assert "action_cancel" in review

def test_services_strings_are_present() -> None:
    strings = read("android/app/src/main/res/values/strings.xml")
    for key in (
        "services_workspace_title",
        "services_workspace_body",
        "services_workspace_filters_label",
        "service_filter_all",
        "service_filter_running",
        "service_filter_enabled",
        "service_filter_stale",
        "service_filter_failed",
        "service_action_review_title",
        "action_preview_command",
    ):
        assert f'name="{key}"' in strings

def test_needs_attention_filter_does_not_treat_normal_logs_or_stopped_state_as_errors() -> None:
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    assert "service.journalText.isNotBlank" not in policy
    assert '"inactive"' not in policy.split("fun serviceNeedsAttention", 1)[1].split("fun serviceMatchesWorkspaceFilter", 1)[0]
    assert '"unknown"' not in policy.split("fun serviceNeedsAttention", 1)[1].split("fun serviceMatchesWorkspaceFilter", 1)[0]
    assert "attentionTokens" in policy
