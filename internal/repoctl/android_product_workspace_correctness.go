package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateAndroidProductWorkspaceCorrectness keeps CHR19 executable instead of prose-only.
// It seals the Android product/workspace fixes around Home metrics/CTAs, launcher
// preview routing, stale cached workspaces, Storage accuracy, Logs freshness and
// service-journal failure visibility.
func ValidateAndroidProductWorkspaceCorrectness(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR19 read %s: %w", rel, err)
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
				return fmt.Errorf("CHR19 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}

	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt",
		"destination: String = \"chroots\"",
		"rootfsBytesReliable",
		"mismatchedMountCount",
		"snapshotBytesReliable",
		"truncated: Boolean",
		"refreshedAt: Long",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
		"Result<LogsPane>",
		"rootfsBytesReliable",
		"snapshotByteErrorCount",
		"operations.count { !it.stale }",
		"destination = \"activity\"",
		"journal.firstString(\"error\", \"readError\", \"read_error\")",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt",
		"logsRefreshSerial",
		"requestSerial == logsRefreshSerial",
		"rows.none { it.name == selected }",
		"stale = logsPane.value.entries.isNotEmpty()",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt",
		"snapshot.recommendedAction.destination",
		"recommendedActionLabel",
		"\"install\" -> onOpenInstall",
		"\"refresh\" -> onRefresh",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt",
		"onSelect(); onPreviewSnapshotCreate(chroot.name)",
		"workspaceSizeLabel",
		"logEntryDisplay",
		"storage_size_estimate_title",
		"logs_snapshot_truncated",
		"when (effectiveTab)",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/common.go",
		"type DirectoryUsage struct",
		"SkippedMounts int",
		"return filepath.SkipDir",
		"func directoryUsage",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/chroots.go",
		"rootUsage := directoryUsage(root)",
		"snapshotUsage := directoryUsage(snapshotDirectory)",
		"rootfsBytesReliable",
		"mismatchedMountCount",
		"snapshotBytesReliable",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/system.go",
		"readRecentLogLines",
		"Truncated: truncated",
		"ReadError: \"\"",
		"RefreshedAt: time.Now().UTC().Format(time.RFC3339Nano)",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/response_schemas.go",
		"count",
		"truncated",
		"readError",
		"workspace",
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/roadmap-coverage.json",
		`"id": "CHR19"`,
		`"title": "Android product/workspace correctness"`,
		`"ownerOverlay": "CHR19"`,
		`"status": "implemented"`,
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR19_ANDROID_PRODUCT_WORKSPACE_CORRECTNESS.md",
		"Android product/workspace correctness",
		"ValidateAndroidProductWorkspaceCorrectness",
	); err != nil {
		return err
	}
	return nil
}
