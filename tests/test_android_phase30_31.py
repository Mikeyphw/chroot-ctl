from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase30_31_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate-android-phase30-31.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_adaptive_shell_has_five_stable_primary_destinations() -> None:
    shell = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AdaptiveNavigationShell.kt")
    assert "NavigationBar" in shell
    assert "NavigationRail" in shell
    destination = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/AppDestination.kt")
    for item in ("Home", "Chroots", "Install", "Activity", "Tools"):
        assert f"    {item}(" in destination
    assert "private val primaryDestinations: List<AppDestination> = AppDestination.entries.toList()" in shell
    assert "Help(" not in destination


def test_home_keeps_cached_content_visible_during_refresh_failure() -> None:
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    ready = home.split("private fun HomeReady", 1)[1]
    assert "if (refreshState is RefreshState.Failed)" in ready
    assert "RefreshFailureBanner(" in ready
    assert "DashboardOverview(" in ready


def test_raw_transport_failure_is_disclosed_only_as_technical_detail() -> None:
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    strings = read("android/app/src/main/res/values/strings.xml")
    assert "technicalDetails = message" in home
    assert "technicalDetails = refreshState.message" in home
    assert "DeadObjectException" not in strings


def test_sdk_and_strict_lint_contract_are_preserved() -> None:
    build = read("android/app/build.gradle.kts")
    lint = read("android/app/lint.xml")
    assert "compileSdk = 37" in build
    assert "targetSdk = 36" in build
    assert "warningsAsErrors = true" in build
    assert "abortOnError = true" in build
    assert lint.count('severity="ignore"') == 1
    assert 'id="OldTargetApi" severity="ignore"' in lint
