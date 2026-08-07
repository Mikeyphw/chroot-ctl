from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase38_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate-android-phase38.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_system_users_are_collapsed_by_default_and_login_users_remain_visible() -> None:
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    users = source.split("private fun UsersPanel", 1)[1].split("private fun ServicesPanel", 1)[0]
    assert "mutableStateOf(UserWorkspaceFilter.Managed.name)" in users
    assert "systemUsers = userList.filter(::userIsSystem)" in users
    assert "action_show_system_users" in users
    assert 'user.username.equals("root", ignoreCase = true)' in policy
    assert '"daemon"' in policy
    assert '"/usr/sbin/nologin"' in policy
    assert "SYSTEM_USER_UID_THRESHOLD = 1000" in policy


def test_user_rows_are_compact_and_do_not_execute_mutations() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    users = source.split("private fun UsersPanel", 1)[1].split("private fun ServicesPanel", 1)[0]
    row = users.split("private fun FocusedUserRow", 1)[1].split("private fun UserActionReviewSheet", 1)[0]
    assert "private fun UserRow(" not in users
    assert "action_review_user_actions" in row
    assert "onPreviewUserPayload" not in row
    assert "onStartUserOperation" not in row
    assert row.count("Button(") <= 1


def test_user_review_sheet_owns_preview_execution_and_confirmation() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    users = source.split("private fun UsersPanel", 1)[1].split("private fun ServicesPanel", 1)[0]
    review = users.split("private fun UserActionReviewSheet", 1)[1].split("private fun UserActionSelector", 1)[0]
    assert "onPreviewUserPayload(payload)" in review
    assert "onStartUserOperation(operation, payload)" in review
    assert "confirmation == username" in review
    assert "password.isNotBlank() && password == confirmPassword" in review
    assert "PasswordVisualTransformation" in review


def test_services_and_bridge_shape_promises_are_preserved() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    services = source.split("private fun ServicesPanel", 1)[1].split("private fun userPayload", 1)[0]
    assert "FocusedServiceRow" in services
    assert "ServiceActionReviewSheet" in services
    assert 'requireDataOrWrappedArray("checks", "system.status")' in repository
    assert 'requireArrayFromData("users", "items")' in repository
    assert 'requireArrayFromData("services", "items")' in repository


def test_review_state_token_cannot_collide_with_linux_username() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    users = source.split("private fun UsersPanel", 1)[1].split("private fun ServicesPanel", 1)[0]
    assert 'ADD_USER_REVIEW_TOKEN = "add:"' in users
    assert 'USER_REVIEW_TOKEN_PREFIX = "user:"' in users
    assert "reviewUserToken = userReviewToken(user.username)" in users
    assert "reviewUsername(reviewUserToken)" in users
    assert 'ADD_USER_REVIEW_TOKEN = "__add_user__"' not in users
