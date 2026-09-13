package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateCRUDAtomicity is the executable CHR07 source seal. Behavioral
// rollback/crash tests live with services, mutation, registry and config; this
// guard prevents destructive CRUD from drifting back to split identities or
// best-effort journal transitions.
func ValidateCRUDAtomicity(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR07 read %s: %w", rel, err)
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
				return fmt.Errorf("CHR07 %s missing invariant %q", rel, token)
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
				return fmt.Errorf("CHR07 %s retains forbidden invariant %q", rel, token)
			}
		}
		return nil
	}

	if err := require("internal/services/common.go",
		"func validateRegisteredTargetPath", "filepath.Base(clean) != name",
		"management root", "reserved management storage"); err != nil {
		return err
	}
	if err := require("internal/services/crud_namespace.go",
		"destructiveTarget", "requireFullyUnmounted", "requireNoManagedServiceActivity",
		"renameNamespacePlan", "removeNamespacePlan", "ServiceStateDir", "ServiceLogDir",
		"targets", ".enabled", "ChrootOverrides", "snapshot path escapes chroot snapshot namespace",
		"cleanupCrudMoves", "mutation.SyncDir"); err != nil {
		return err
	}
	if err := require("internal/services/chroots.go",
		"RenameIdentity", "namespace_moves", "config_override", "snapshot_old_root", "snapshot_new_root",
		"FSMutationStaged", "FSMutationPromoting", "FSMutationCommitted", "FSMutationCleanupDebt",
		"FSMutationRepairRequired", "rollbackRename", "rollbackRemove", "tombstone"); err != nil {
		return err
	}
	chrootsBody, err := read("internal/services/chroots.go")
	if err != nil {
		return err
	}
	overrideCommit := strings.Index(chrootsBody, "migrateOverride(plan, oldName, newName, false)")
	registryCommit := strings.Index(chrootsBody, "if e = crudRegistryRenameIdentity")
	if overrideCommit < 0 || registryCommit < 0 || overrideCommit >= registryCommit {
		return fmt.Errorf("CHR07 rename must keep persisted override migration rollback-able before registry identity commit")
	}
	if err := forbid("internal/services/chroots.go", "oldCfg, _ :=", "newCfg, _ :="); err != nil {
		return err
	}
	if err := require("internal/config/override_mutation.go",
		"RewriteChrootOverride", "os.CreateTemp", "tmp.Sync()", "os.Rename", "d.Sync()"); err != nil {
		return err
	}
	if err := require("internal/registry/registry.go",
		"func (r *Registry) RenameIdentity", "UPDATE snapshots SET path", "RowsAffected",
		"path escapes old namespace"); err != nil {
		return err
	}
	if err := require("internal/mutation/recovery.go",
		"m.Kind != \"chroot-rename\" || detailString(m, \"new_name\") != target",
		"namespace_moves", "finishRecoveryMoves", "rollbackRecoveryMoves", "recoverConfigOverride",
		"FSMutationCleanupDebt", "FSMutationRepairRequired", "SyncDir(filepath.Dir(path))"); err != nil {
		return err
	}
	if err := require("internal/cli/dispatch.go", "Known Chroots"); err != nil {
		return err
	}

	// U155/U156 are owned by CHR07 even though CHR06 introduced the underlying
	// transfer transaction. Seal the ordering: the backup identity must be in
	// the durable mutation detail before the first target->backup rename, and a
	// failed old-backup deletion must become cleanup debt rather than disappear.
	transfer, err := read("internal/services/transfer.go")
	if err != nil {
		return err
	}
	begin := strings.Index(transfer, `"backup": backup`)
	displace := strings.Index(transfer, "os.Rename(target, backup)")
	if begin < 0 || displace < 0 || begin >= displace {
		return fmt.Errorf("CHR07 transfer import must persist backup identity before target displacement")
	}
	if !strings.Contains(transfer[displace:], "FSMutationCleanupDebt") {
		return fmt.Errorf("CHR07 transfer import must preserve backup-cleanup failure as cleanup debt")
	}
	return nil
}
