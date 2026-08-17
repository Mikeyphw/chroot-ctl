from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="strict")


def lint_issues() -> dict[str, str]:
    root = ET.parse(ROOT / "android/app/lint.xml").getroot()
    return {
        issue.attrib.get("id", ""): issue.attrib.get("severity", "")
        for issue in root.findall("issue")
    }


def test_phase29c_keeps_sdk_36_and_strict_lint() -> None:
    build = read("android/app/build.gradle.kts")
    assert "compileSdk = 37" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    assert 'lintConfig = file("lint.xml")' in build
    assert "warningsAsErrors = false" not in build


def test_phase29c_ignores_only_old_target_api() -> None:
    ignored = {issue_id for issue_id, severity in lint_issues().items() if severity == "ignore"}
    assert ignored == {"OldTargetApi"}


def test_phase29c_has_no_wildcard_or_gradle_lint_disable() -> None:
    issues = lint_issues()
    build = read("android/app/build.gradle.kts")
    assert "all" not in issues
    assert "*" not in issues
    assert "disable +=" not in build
    assert "disable.add" not in build
