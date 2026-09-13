package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateSnapshotFidelity is the executable CHR09 source seal. It prevents
// metadata-lossy snapshot/import paths and split snapshot authority from
// re-entering the release after the behavioral suites have passed.
func ValidateSnapshotFidelity(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR09 read %s: %w", rel, err)
		}
		return string(b), nil
	}
	require := func(rel string, tokens ...string) error {
		body, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if !strings.Contains(body, token) {
				return fmt.Errorf("CHR09 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	forbid := func(rel string, tokens ...string) error {
		body, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if strings.Contains(body, token) {
				return fmt.Errorf("CHR09 %s retains forbidden invariant %q", rel, token)
			}
		}
		return nil
	}

	if err := require("internal/fsmeta/archive_linux.go", "ArchiveTreeGzip", "ExtractTarRoot", "Lchown", "CHROOTCTL.xattr.", "TypeLink", "TypeFifo", "TypeChar", "TypeBlock", "socket"); err != nil {
		return err
	}
	if err := require("internal/services/snapshot_archive.go", "rootfs.tar.gz", "manifest.json", "rootfs-tar-v1", "ProtectedOperationID", "MetadataContract", "requireSnapshotMetadataContract"); err != nil {
		return err
	}
	if err := require("internal/services/snapshots.go", "BaseConfig.SnapshotDir", "writeSnapshotPayload", "readSnapshotManifest", "requireUnmounted", "legacy", "snapshotKindRootfsTarV1", "validation.SnapshotNameField"); err != nil {
		return err
	}
	if err := forbid("internal/services/snapshots.go", "func copyTree(", `filepath.Join(s.C.BaseConfig.ChrootRoot, ".snapshots")`); err != nil {
		return err
	}
	if err := require("internal/services/transfer.go", "fsmeta.ExtractTarRoot", "rootfs_metadata_contract", "chrootctl-rootfs-v1", "--numeric-owner", "--acls", "--xattrs", "--sparse", "--one-file-system"); err != nil {
		return err
	}
	if err := require("internal/services/install.go", "uniqueSnapshotName", "Snapshots().Create"); err != nil {
		return err
	}
	if err := require("internal/bridge/dispatcher.go", "WithOperationProvenance"); err != nil {
		return err
	}
	if err := require("internal/cli/dispatch.go", "func (a *App) snapshots", "Snapshots().Create", "Snapshots().Restore", "Snapshots().Export"); err != nil {
		return err
	}
	contract, err := read("migration/contracts/v1/cli.json")
	if err != nil {
		return err
	}
	for _, token := range []string{`"command": "snapshots"`, `"command": "snapshots create"`, `"command": "snapshots restore"`, `"command": "snapshots export"`} {
		if !strings.Contains(contract, token) {
			return fmt.Errorf("CHR09 CLI contract missing %q", token)
		}
	}
	if err := require("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt", "matchingRecoverySnapshot", "protected_operation_id", "defaultSnapshotName"); err != nil {
		return err
	}
	if err := require("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt", "snapshots.export", "adoptSnapshotExport", "onCreateExportDocument", "ChrootWorkspaceTab.Snapshots", "exported_archive", "resultJson"); err != nil {
		return err
	}
	if err := require("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt", "resultJson = resultJson", "operation_succeeded", "payload.opt(\"result\")"); err != nil {
		return err
	}
	return nil
}
