#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def main() -> int:
    errors: list[str] = []
    build = read("android/app/build.gradle.kts")
    lint_path = ROOT / "android/app/lint.xml"
    docs = read("docs/android/PHASE_29C_SDK36_LINT_POLICY_HOTFIX.md")

    def error_if(condition: bool, message: str) -> None:
        if condition:
            errors.append(message)

    error_if("compileSdk = 37" not in build, "compileSdk must be pinned to 37")
    error_if("targetSdk = 36" not in build, "targetSdk must remain pinned to 36")
    error_if("warningsAsErrors = true" not in build, "lint warnings must remain errors")
    error_if("abortOnError = true" not in build, "lint must continue aborting on errors")
    error_if('lintConfig = file("lint.xml")' not in build, "app lint.xml must remain wired")
    error_if("warningsAsErrors = false" in build, "lint warnings must not be globally demoted")
    error_if("disable +=" in build or "disable.add" in build, "lint issues must not be broadly disabled in Gradle")

    try:
        root = ET.parse(lint_path).getroot()
    except (ET.ParseError, OSError) as exc:
        errors.append(f"lint.xml must be readable XML: {exc}")
        root = ET.Element("lint")

    issues = {
        issue.attrib.get("id", ""): issue.attrib.get("severity", "")
        for issue in root.findall("issue")
    }
    expected_ignored = {"OldTargetApi"}
    actual_ignored = {issue_id for issue_id, severity in issues.items() if severity == "ignore"}

    error_if(issues.get("OldTargetApi") != "ignore", "OldTargetApi must be narrowly ignored in lint.xml")
    error_if(actual_ignored != expected_ignored, f"unexpected ignored lint issue set: {sorted(actual_ignored)}")
    error_if("all" in issues or "*" in issues, "lint.xml must not contain a wildcard suppression")

    for token in (
        "SDK 36 remains pinned",
        "OldTargetApi",
        "warningsAsErrors",
        "No other lint issue",
    ):
        error_if(token not in docs, f"phase29c documentation missing token: {token}")

    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1

    print("Phase 29C SDK 36 lint policy validator passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
