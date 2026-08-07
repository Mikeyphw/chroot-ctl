from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_phase35_36_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate-android-phase35-36.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

def test_top_level_chroots_page_is_a_workspace_launcher() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    assert "ChrootWorkspaceLauncher" in source
    assert "ChrootWorkspaceScreen" in source
    compact_card = source.split("private fun Phase32ChrootCard", 1)[1].split("private fun ChrootWorkspaceScreen", 1)[0]
    assert "action_open_workspace" in compact_card
    assert "UsersPanel(" not in compact_card
    assert "ServicesPanel(" not in compact_card
    assert 'onPreviewLifecycle(chroot.name, "remove")' not in compact_card

def test_workspace_tabs_hold_the_heavy_chroot_surfaces() -> None:
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    workspace = source.split("private fun ChrootWorkspaceScreen", 1)[1]
    for token in (
        "ChrootWorkspaceTab.Overview",
        "ChrootWorkspaceTab.Services",
        "ChrootWorkspaceTab.Users",
        "ChrootWorkspaceTab.Snapshots",
        "ChrootWorkspaceTab.Advanced",
        "WorkspaceOverviewTab",
        "AdvancedWorkspaceTab",
    ):
        assert token in workspace
    assert "LifecyclePanel(" in source.split("private fun AdvancedWorkspaceTab", 1)[1]

def test_bridge_shape_adapter_handles_array_detail_and_wrapped_lists() -> None:
    bridge = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModels.kt")
    repo = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    assert "requireDataOrWrappedArray" in bridge
    assert "requireArrayFromData" in bridge
    assert 'requireDataOrWrappedArray("checks", "system.status")' in repo
    assert 'requireDataOrWrappedArray("checks", "system.doctor")' in repo
    assert 'requireArrayFromData("services", "items")' in repo
    assert 'requireArrayFromData("users", "items")' in repo
    assert 'requireArrayFromData("snapshots", "items")' in repo

def test_raw_bridge_shape_error_is_not_the_primary_chroots_message() -> None:
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt")
    source = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    assert "bridgeShapePrimaryMessage" in policy
    assert "BridgePaneError" in source
    assert "PathText(message.take(1200)" in source
