package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateMutationEngineGateA is the executable CHR06 / Gate A source seal.
// Behavioral concurrency, dry-run and crash-recovery tests live in their owning
// packages; this seal prevents the shared boundary from drifting back to
// transport-specific locks or best-effort journal transitions.
func ValidateMutationEngineGateA(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("Gate A read %s: %w", rel, err)
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
				return fmt.Errorf("Gate A %s missing invariant %q", rel, token)
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
				return fmt.Errorf("Gate A %s retains forbidden invariant %q", rel, token)
			}
		}
		return nil
	}

	if err := require("internal/mutation/locking.go", "global-mutating", "LOCK_SH", "target-", "AcquireScope", "heldMode", "cannot upgrade held shared mutation lock"); err != nil {
		return err
	}
	if err := require("internal/mutation/engine.go", "type Engine struct", "func (e *Engine) Guard", "func (e *Engine) Begin", "FSMutationFailed", "SyncDir"); err != nil {
		return err
	}
	if err := require("internal/mutation/recovery.go", "RecoverLocked", "chroot-remove", "chroot-rename", "snapshot.restore", "chroot.import", "install.extract", "catalog.apply", "FSMutationRepairRequired", "FSMutationCleanupDebt"); err != nil {
		return err
	}
	if err := forbid("internal/mutation/recovery.go", "_ = e.Registry.UpdateFSMutation"); err != nil {
		return err
	}

	if err := require("internal/services/container.go", "config.LoadReadOnly", "registry.OpenReadOnly", "registry.OpenEphemeral", "logging.ConfigureReadOnly", "Mutations", "RecoverFilesystemMutations"); err != nil {
		return err
	}
	if err := require("internal/registry/registry.go", "FSMutationCleanupDebt", "FSMutationRepairRequired", "RowsAffected", "OpenEphemeral", "query_only"); err != nil {
		return err
	}
	if err := require("internal/operations/recovery.go", "ListActive"); err != nil {
		return err
	}
	if err := require("internal/operations/journal.go", "func (j *Journal) ListActive", "dir.Sync()"); err != nil {
		return err
	}
	if err := require("internal/operations/manager.go", "mutation.AcquireScope", "persistTerminal"); err != nil {
		return err
	}

	if err := require("internal/cli/cli.go", "cliMutationScope", "s.Mutations.Guard", "RecoverFilesystemMutations"); err != nil {
		return err
	}
	if err := require("internal/bridge/dispatcher.go", "d.Mutations.RecoverLocked", "d.Operations == nil"); err != nil {
		return err
	}

	if err := require("internal/services/chroots.go", "FSMutationStaged", "FSMutationPromoting", "FSMutationCommitted", "FSMutationRolledBack", "FSMutationRepairRequired", "tombstone"); err != nil {
		return err
	}
	if err := require("internal/services/snapshots.go", "FSMutationStaged", "FSMutationPromoting", "FSMutationCommitted", "FSMutationCleanupDebt", "backup"); err != nil {
		return err
	}
	if err := require("internal/services/transfer.go", "s.C.DryRun", "FSMutationStaged", "FSMutationPromoting", "FSMutationCommitted", "FSMutationCleanupDebt", "_chrootctl_mutation_id"); err != nil {
		return err
	}
	if err := require("internal/install/base.go", "FSMutationStaged", "FSMutationPromoting", "FSMutationCommitted", "FSMutationCleanupDebt", "persistErr := b.RecordStep", "persistErr := transition(registry.FSMutationRepairRequired"); err != nil {
		return err
	}
	if err := require("internal/system/system.go", "func (r *Runner) RequireRoot() error", "r.DryRun"); err != nil {
		return err
	}
	for _, rel := range []string{"internal/controller/controller.go", "internal/install/ubuntu/ubuntu.go", "internal/install/arch/arch.go", "internal/users/users.go"} {
		if err := forbid(rel, "sys.RequireRoot()"); err != nil {
			return err
		}
	}
	for _, rel := range []string{"internal/services/chroots.go", "internal/services/snapshots.go", "internal/services/transfer.go", "internal/install/base.go", "internal/catalog/catalog.go"} {
		if err := forbid(rel, "_ = s.C.Registry.UpdateFSMutation", "_ = b.Registry.UpdateFSMutation"); err != nil {
			return err
		}
	}

	if err := require("internal/catalog/catalog.go", "runner.DryRun", "persist catalog failure state"); err != nil {
		return err
	}
	if err := require("internal/services/support.go", "if s.C.DryRun"); err != nil {
		return err
	}
	if err := require("internal/cli/dispatch.go", "clipboard.daemon.start", "clipboard.set", "dryRun", "Magisk module"); err != nil {
		return err
	}
	if err := require("internal/install/factory/factory.go", "FetchText = fetchText", "Download = download", "curl"); err != nil {
		return err
	}

	raw, err := os.ReadFile(filepath.Join(root, "migration/contracts/v1/cli.json"))
	if err != nil {
		return err
	}
	var contract struct {
		CommandNodes []struct{ Command, Mutability string } `json:"commandNodes"`
	}
	if err := json.Unmarshal(raw, &contract); err != nil {
		return fmt.Errorf("parse CLI contract for Gate A: %w", err)
	}
	need := map[string]bool{"chroots export": false, "transfer export": false}
	for _, node := range contract.CommandNodes {
		if _, ok := need[node.Command]; ok && node.Mutability == "mutate" {
			need[node.Command] = true
		}
	}
	for command, ok := range need {
		if !ok {
			return fmt.Errorf("Gate A command %q must be mutation-classified", command)
		}
	}
	return nil
}
