package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateNavigationAdaptiveFinalReleaseSeal seals CHR20 as an executable final gate.
// It keeps the navigation/adaptive/accessibility release promises out of prose-only
// documentation by checking the runtime policies, Android source wiring, final gate
// commands, and roadmap closure artifacts together.
func ValidateNavigationAdaptiveFinalReleaseSeal(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR20 read %s: %w", rel, err)
		}
		return string(b), nil
	}
	mustContain := func(rel string, tokens ...string) error {
		text, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if !strings.Contains(text, token) {
				return fmt.Errorf("CHR20 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}

	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/NavigationReleasePolicy.kt",
		"object NavigationReleasePolicy",
		"sanitizeDestinationStack",
		"pushDestinationStack",
		"popDestinationStack",
		"deepLinkDecision",
		"WaitForSnapshot",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt",
		"BackHandler",
		"destinationStack",
		"pendingOperationDeepLinkId",
		"NavigationReleasePolicy.deepLinkDecision",
		"viewModel.ensureDestinationLoaded(destination)",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt",
		"destinationWarmups",
		"ensureDestinationLoaded(destination: AppDestination)",
		"AppDestination.Tools",
		"refreshDebugWorkbench()",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/AdaptiveLayoutPolicy.kt",
		"MAX_RAIL_FONT_SCALE",
		"availableHeightDp",
		"releaseWindowProfile(availableWidthDp, availableHeightDp)",
		"fontScale < MAX_RAIL_FONT_SCALE",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AdaptiveNavigationShell.kt",
		"maxHeight.value",
		"density.fontScale",
		"val navigationType = primaryNavigationType",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AppCards.kt",
		"LiveRegionMode.Polite",
		"releaseSelectionSemantics",
		"stateDescription = if (selected)",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt",
		"restoreWorkspaceNameOrNull",
		"restoredWorkspaceUnavailable",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt",
		"availableWorkspaceNames",
		"restoreWorkspaceNameOrNull(workspaceName, availableWorkspaceNames)",
		"releaseSelectionSemantics(selected)",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicy.kt",
		"system-predictive-back-stack",
		"notification-deeplink-proved-before-navigation",
		"runtime-window-policy-executable",
		"androidInstrumentationSealChecks",
		"go run ./cmd/repoctl validate",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/NavigationReleasePolicyChr20Test.kt",
		"notification deep links must be proven before navigation",
		"adaptive policy uses height and font scale not width alone",
		"restored removed workspace names are discarded",
	); err != nil {
		return err
	}
	if err := mustContain(".devtool-artifact/validate.sh",
		"go run ./cmd/repoctl validate",
		":chrootctlAndroidAppSeal",
		":chrootctlAndroidLintConfigurationSeal",
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/roadmap-coverage.json",
		`"id": "CHR20"`,
		`"title": "Navigation, adaptive UI & final release seal"`,
		`"ownerOverlay": "CHR20"`,
		`"status": "implemented"`,
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR20_NAVIGATION_ADAPTIVE_FINAL_RELEASE_SEAL.md",
		"Navigation, adaptive UI & final release seal",
		"ValidateNavigationAdaptiveFinalReleaseSeal",
	); err != nil {
		return err
	}
	return nil
}
