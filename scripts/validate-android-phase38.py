#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise AssertionError(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    chroots = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    workflow_test = read("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicyTest.kt")
    phase37_validator = read("scripts/validate-android-phase37.py")
    strings_path = ROOT / "android/app/src/main/res/values/strings.xml"
    ET.parse(strings_path)
    strings = strings_path.read_text(encoding="utf-8")

    require("enum class UserWorkspaceFilter" in policy, "user workspace filter enum missing")
    for token in (
        "UserWorkspaceFilter.Managed",
        "UserWorkspaceFilter.LoginUsers",
        "UserWorkspaceFilter.SystemUsers",
        "userWorkspaceFilters",
        "selectedUserWorkspaceFilter",
        "userHasLoginShell",
        "userIsSystem",
        "userMatchesWorkspaceFilter",
        "SYSTEM_USER_UID_THRESHOLD = 1000",
    ):
        require(token in policy, f"user workspace policy missing {token}")
    root_branch = policy.split("fun userIsSystem", 1)[1].split("fun userIsManaged", 1)[0]
    require('user.username.equals("root", ignoreCase = true)' in root_branch, "root special-case visibility is not documented in policy code")
    require("knownSystemUsernames" in policy and '"daemon"' in policy, "known system-account classifier missing")
    require('"/usr/sbin/nologin"' in policy and '"/bin/false"' in policy, "no-login shell classifier missing")

    require("private fun UsersPanel" in chroots, "UsersPanel missing")
    users = chroots.split("private fun UsersPanel", 1)[1].split("private fun ServicesPanel", 1)[0]
    for token in (
        "UserFilterButton",
        "FocusedUserRow",
        "UserActionReviewSheet",
        "userWorkspaceFilters().forEach",
        "selectedUserWorkspaceFilter",
        "userMatchesWorkspaceFilter",
        "action_show_system_users",
        "action_review_user_actions",
        "action_review_add_user",
        "action_preview_command",
    ):
        require(token in users, f"focused users workspace missing {token}")

    require("private fun UserRow(" not in users, "old per-user action matrix still present")
    focused_row = users.split("private fun FocusedUserRow", 1)[1].split("private fun UserActionReviewSheet", 1)[0]
    require("onPreviewUserPayload" not in focused_row, "user row previews directly instead of opening review sheet")
    require("onStartUserOperation" not in focused_row, "user row executes directly instead of opening review sheet")
    require("action_review_user_actions" in focused_row, "compact user row does not route to review sheet")
    require(focused_row.count("Button(") <= 1, "focused user row regressed into a permanent button matrix")

    review = users.split("private fun UserActionReviewSheet", 1)[1].split("private fun UserActionSelector", 1)[0]
    require("onPreviewUserPayload(payload)" in review, "preview is not owned by the user review sheet")
    require("onStartUserOperation(operation, payload)" in review, "execution is not owned by the user review sheet")
    require("confirmation == username" in review, "password/remove exact-user confirmation missing")
    require("password.isNotBlank() && password == confirmPassword" in review, "password matching gate missing")
    require("PasswordVisualTransformation" in review, "password fields are not visually protected")

    users_panel = users.split("private fun UserFilterButton", 1)[0]
    require("mutableStateOf(UserWorkspaceFilter.Managed.name)" in users_panel, "default user filter is not Managed")
    require("systemUsers = userList.filter(::userIsSystem)" in users_panel, "system-user collapsed count missing")
    require("filter != UserWorkspaceFilter.SystemUsers" in users_panel, "system users are not collapsed by default")
    require('ADD_USER_REVIEW_TOKEN = "add:"' in users, "add-user review state token is not namespace-safe")
    require('USER_REVIEW_TOKEN_PREFIX = "user:"' in users, "user review state token prefix missing")
    require("reviewUserToken = userReviewToken(user.username)" in users, "user review state stores raw usernames and can collide with add-user sentinel")
    require("reviewUsername(reviewUserToken)" in users, "user review state token is not decoded safely")
    require('ADD_USER_REVIEW_TOKEN = "__add_user__"' not in users, "legacy colliding add-user sentinel remains")

    for key in (
        "users_workspace_title",
        "users_workspace_body",
        "users_workspace_filters_label",
        "user_filter_managed",
        "user_filter_login",
        "user_filter_system",
        "action_show_system_users",
        "action_hide_system_users",
        "user_action_review_title",
        "user_confirmation_exact_label",
    ):
        require(f'name="{key}"' in strings, f"missing string resource {key}")

    require("user workspace hides system accounts by default but keeps normal login users" in workflow_test, "user classifier unit test missing")
    require("user workspace actions keep mutations inside review flow" in workflow_test, "user action policy unit test missing")

    # Preserve Phase 35-36 bridge adapter and workspace shape.
    for token in (
        'requireDataOrWrappedArray("checks", "system.status")',
        'requireDataOrWrappedArray("checks", "system.doctor")',
        'requireArrayFromData("users", "items")',
        'requireArrayFromData("services", "items")',
        'requireArrayFromData("snapshots", "items")',
    ):
        require(token in repository, f"bridge-shape adapter promise missing: {token}")
    require("chrootListIsWorkspaceLauncherOnly(): Boolean = true" in policy, "top-level Chroots launcher promise regressed")
    require("ChrootWorkspaceTab.Services" in policy and "ChrootWorkspaceTab.Users" in policy, "workspace tabs regressed")

    # Preserve Phase 37 service-workspace markers and validator.
    services = chroots.split("private fun ServicesPanel", 1)[1].split("private fun userPayload", 1)[0]
    for token in (
        "FocusedServiceRow",
        "ServiceActionReviewSheet",
        "serviceWorkspaceFilters().forEach",
        "serviceMatchesWorkspaceFilter",
        "action_preview_command",
    ):
        require(token in services, f"Phase 37 Services workspace regressed: {token}")
    require("service.journalText.isNotBlank" not in policy.split("fun serviceNeedsAttention", 1)[1].split("fun serviceMatchesWorkspaceFilter", 1)[0], "Phase 37 needs-attention fix regressed")
    require("Phase 37 focused services workspace validation passed" in phase37_validator, "Phase 37 validator was removed or replaced")

    # Architecture and SDK guardrails.
    build = read("android/app/build.gradle.kts")
    require("compileSdk = 37" in build and "targetSdk = 36" in build, "compileSdk 37 / targetSdk 36 guardrail regressed")
    manifest_and_sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (ROOT / "android/app/src/main").rglob("*")
        if p.is_file() and p.suffix in {".kt", ".xml"}
    )
    require("WebView(" not in manifest_and_sources and "android.webkit.WebView" not in manifest_and_sources, "WebView boundary regressed")
    require("HttpServer" not in manifest_and_sources and "NanoHTTPD" not in manifest_and_sources, "HTTP-server boundary regressed")
    require('check(!capabilities.arbitraryShell)' in repository, "arbitrary-shell bridge safety check regressed")

    print("Phase 38 focused users workspace validation passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
