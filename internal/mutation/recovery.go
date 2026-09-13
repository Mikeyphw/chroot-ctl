package mutation

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"chrootctl/internal/config"
	"chrootctl/internal/registry"
)

type RecoveryReport struct {
	Recovered      []string
	RepairRequired []string
	CleanupDebt    []string
}
type RecoveryRequiredError struct{ Mutations []string }

func (e RecoveryRequiredError) Error() string {
	return "filesystem mutation recovery requires manual review: " + strings.Join(e.Mutations, ", ")
}

func (e *Engine) RecoverLocked(ctx context.Context, target string) (RecoveryReport, error) {
	var report RecoveryReport
	if e == nil || e.DryRun {
		return report, nil
	}
	rows, err := e.Registry.PendingFSMutations(ctx, 0)
	if err != nil {
		return report, err
	}
	for _, m := range rows {
		if target != "" && m.Target != target {
			// Rename cleanup debt is recorded under the old identity because that
			// is the lock/target that existed when the transaction began. Once
			// the registry commit succeeds, subsequent commands address the new
			// identity, so allow that identity to drive recovery as well.
			if m.Kind != "chroot-rename" || detailString(m, "new_name") != target {
				continue
			}
		}
		state, err := e.recoverOne(ctx, m)
		if err != nil {
			if persistErr := e.Registry.UpdateFSMutation(context.WithoutCancel(ctx), m.MutationID, registry.FSMutationRepairRequired, map[string]any{"recovery_error": err.Error()}); persistErr != nil {
				return report, errors.Join(err, fmt.Errorf("persist repair-required state for %s: %w", m.MutationID, persistErr))
			}
			report.RepairRequired = append(report.RepairRequired, m.MutationID)
			continue
		}
		if state == registry.FSMutationCleanupDebt {
			report.CleanupDebt = append(report.CleanupDebt, m.MutationID)
		}
		if state == registry.FSMutationRepairRequired {
			report.RepairRequired = append(report.RepairRequired, m.MutationID)
		} else {
			report.Recovered = append(report.Recovered, m.MutationID)
		}
	}
	if len(report.RepairRequired) > 0 {
		return report, RecoveryRequiredError{Mutations: report.RepairRequired}
	}
	return report, nil
}

func exists(path string) bool {
	if path == "" {
		return false
	}
	_, err := os.Lstat(path)
	return err == nil
}
func detailString(m registry.FSMutation, key string) string {
	if v := m.Detail[key]; v != nil {
		return strings.TrimSpace(fmt.Sprint(v))
	}
	return ""
}
func detailBool(m registry.FSMutation, key string) bool {
	v := m.Detail[key]
	b, _ := v.(bool)
	return b
}
func removeIfExists(path string) error {
	if path == "" || !exists(path) {
		return nil
	}
	if err := os.RemoveAll(path); err != nil {
		return err
	}
	return SyncDir(filepath.Dir(path))
}
func renameIfPossible(from, to string) error {
	if from == "" || to == "" {
		return errors.New("recovery rename path is empty")
	}
	if !exists(from) {
		return fmt.Errorf("recovery source is missing: %s", from)
	}
	if exists(to) {
		return fmt.Errorf("recovery destination already exists: %s", to)
	}
	if err := os.Rename(from, to); err != nil {
		return err
	}
	return SyncDir(filepath.Dir(to))
}

type recoveryMove struct{ From, To string }

func detailMoves(m registry.FSMutation) []recoveryMove {
	raw, _ := m.Detail["namespace_moves"].([]any)
	out := make([]recoveryMove, 0, len(raw))
	for _, item := range raw {
		obj, _ := item.(map[string]any)
		from := strings.TrimSpace(fmt.Sprint(obj["from"]))
		to := strings.TrimSpace(fmt.Sprint(obj["to"]))
		if from != "" && to != "" {
			out = append(out, recoveryMove{from, to})
		}
	}
	return out
}
func finishRecoveryMoves(moves []recoveryMove) error {
	for _, mv := range moves {
		fromExists, toExists := exists(mv.From), exists(mv.To)
		switch {
		case toExists && !fromExists:
			continue
		case fromExists && !toExists:
			if err := os.MkdirAll(filepath.Dir(mv.To), 0755); err != nil {
				return err
			}
			if err := os.Rename(mv.From, mv.To); err != nil {
				return err
			}
			if err := SyncDir(filepath.Dir(mv.To)); err != nil {
				return err
			}
		case fromExists && toExists:
			return fmt.Errorf("recovery namespace has both source and destination: %s / %s", mv.From, mv.To)
		}
	}
	return nil
}
func rollbackRecoveryMoves(moves []recoveryMove) error {
	for i := len(moves) - 1; i >= 0; i-- {
		mv := moves[i]
		fromExists, toExists := exists(mv.From), exists(mv.To)
		if fromExists && !toExists {
			continue
		}
		if !fromExists && toExists {
			if err := os.MkdirAll(filepath.Dir(mv.From), 0755); err != nil {
				return err
			}
			if err := os.Rename(mv.To, mv.From); err != nil {
				return err
			}
			if err := SyncDir(filepath.Dir(mv.From)); err != nil {
				return err
			}
			continue
		}
		if fromExists && toExists {
			return fmt.Errorf("rollback namespace has both source and destination: %s / %s", mv.From, mv.To)
		}
	}
	return nil
}
func cleanupRecoveryMoves(moves []recoveryMove) error {
	for _, mv := range moves {
		if err := removeIfExists(mv.To); err != nil {
			return err
		}
	}
	return nil
}
func recoverConfigOverride(m registry.FSMutation, oldName, newName string, remove bool) error {
	if !detailBool(m, "config_override") {
		return nil
	}
	path := detailString(m, "config_path")
	if path == "" {
		return fmt.Errorf("mutation is missing config path for persisted override")
	}
	_, err := config.RewriteChrootOverride(path, oldName, newName, remove)
	return err
}
func (e *Engine) recoverOne(ctx context.Context, m registry.FSMutation) (string, error) {
	if m.State == registry.FSMutationRepairRequired {
		return registry.FSMutationRepairRequired, nil
	}
	switch m.Kind {
	case "chroot-remove":
		return e.recoverRemove(ctx, m)
	case "chroot-rename":
		return e.recoverRename(ctx, m)
	case "snapshot.create":
		return e.recoverSnapshotCreate(ctx, m)
	case "snapshot.restore":
		return e.recoverPromotion(ctx, m, false)
	case "chroot.import":
		return e.recoverPromotion(ctx, m, true)
	case "install.extract":
		return e.recoverPromotion(ctx, m, true)
	case "catalog.apply":
		if m.State == registry.FSMutationCommitted {
			if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationComplete, map[string]any{"recovered": true}); err != nil {
				return "", err
			}
			return registry.FSMutationComplete, nil
		}
		if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationRepairRequired, map[string]any{"recovery": "catalog script outcome is not safely reversible"}); err != nil {
			return "", err
		}
		return registry.FSMutationRepairRequired, nil
	default:
		return "", fmt.Errorf("unsupported pending filesystem mutation kind %q", m.Kind)
	}
}

func (e *Engine) recoverRemove(ctx context.Context, m registry.FSMutation) (string, error) {
	src, tomb := m.SourcePath, m.DestinationPath
	rec, err := e.Registry.Get(ctx, m.Target)
	if err != nil {
		return "", err
	}
	moves := detailMoves(m)
	if m.State == registry.FSMutationCommitted || m.State == registry.FSMutationCleanupDebt || rec == nil {
		if err := removeIfExists(tomb); err != nil {
			return registry.FSMutationCleanupDebt, err
		}
		if err := cleanupRecoveryMoves(moves); err != nil {
			return registry.FSMutationCleanupDebt, err
		}
		if err := recoverConfigOverride(m, m.Target, "", true); err != nil {
			return registry.FSMutationCleanupDebt, err
		}
		if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationComplete, map[string]any{"recovered": true}); err != nil {
			return "", err
		}
		return registry.FSMutationComplete, nil
	}
	if err := rollbackRecoveryMoves(moves); err != nil {
		return "", err
	}
	if exists(tomb) {
		if exists(src) {
			return "", fmt.Errorf("remove recovery found both source and tombstone")
		}
		if err := renameIfPossible(tomb, src); err != nil {
			return "", err
		}
	}
	if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationRolledBack, map[string]any{"recovered": true}); err != nil {
		return "", err
	}
	return registry.FSMutationRolledBack, nil
}

func (e *Engine) recoverRename(ctx context.Context, m registry.FSMutation) (string, error) {
	src, dst := m.SourcePath, m.DestinationPath
	oldRec, err := e.Registry.Get(ctx, m.Target)
	if err != nil {
		return "", err
	}
	newName := detailString(m, "new_name")
	var newRec *registry.Chroot
	if newName != "" {
		newRec, err = e.Registry.Get(ctx, newName)
		if err != nil {
			return "", err
		}
	}
	moves := detailMoves(m)
	if newRec != nil && filepath.Clean(newRec.Path) == filepath.Clean(dst) && exists(dst) {
		if err := finishRecoveryMoves(moves); err != nil {
			return "", err
		}
		if err := recoverConfigOverride(m, m.Target, newName, false); err != nil {
			return registry.FSMutationCleanupDebt, err
		}
		if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationComplete, map[string]any{"recovered": true}); err != nil {
			return "", err
		}
		return registry.FSMutationComplete, nil
	}
	if oldRec != nil {
		// Configuration may already have crossed the old->new boundary even
		// though the registry commit did not. Reverse it before restoring the
		// old filesystem namespace. RewriteChrootOverride is idempotent when the
		// new key was never published.
		if err := recoverConfigOverride(m, newName, m.Target, false); err != nil {
			return "", err
		}
		if err := rollbackRecoveryMoves(moves); err != nil {
			return "", err
		}
		if exists(dst) && !exists(src) {
			if err := renameIfPossible(dst, src); err != nil {
				return "", err
			}
		}
		if !exists(src) {
			return "", fmt.Errorf("rename recovery cannot find authoritative source path")
		}
		if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationRolledBack, map[string]any{"recovered": true}); err != nil {
			return "", err
		}
		return registry.FSMutationRolledBack, nil
	}
	return "", fmt.Errorf("rename recovery cannot identify authoritative registry owner")
}

func (e *Engine) recoverSnapshotCreate(ctx context.Context, m registry.FSMutation) (string, error) {
	stage := detailString(m, "stage")
	name := detailString(m, "snapshot")
	if name != "" {
		if snap, err := e.Registry.GetSnapshotByName(ctx, m.Target, name); err == nil && filepath.Clean(snap.Path) == filepath.Clean(m.DestinationPath) && exists(m.DestinationPath) {
			_ = removeIfExists(stage)
			if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationComplete, map[string]any{"recovered": true}); err != nil {
				return "", err
			}
			return registry.FSMutationComplete, nil
		}
	}
	if err := removeIfExists(stage); err != nil {
		return "", err
	}
	if err := removeIfExists(m.DestinationPath); err != nil {
		return "", err
	}
	if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationRolledBack, map[string]any{"recovered": true}); err != nil {
		return "", err
	}
	return registry.FSMutationRolledBack, nil
}

func (e *Engine) recoverPromotion(ctx context.Context, m registry.FSMutation, registryBound bool) (string, error) {
	stage := detailString(m, "stage")
	backup := detailString(m, "backup")
	target := m.DestinationPath
	if m.State == registry.FSMutationCommitted || m.State == registry.FSMutationCleanupDebt {
		if backup != "" && exists(backup) {
			if err := removeIfExists(backup); err != nil {
				if persistErr := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationCleanupDebt, map[string]any{"cleanup_error": err.Error()}); persistErr != nil {
					return "", errors.Join(err, persistErr)
				}
				return registry.FSMutationCleanupDebt, nil
			}
		}
		_ = removeIfExists(stage)
		if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationComplete, map[string]any{"recovered": true}); err != nil {
			return "", err
		}
		return registry.FSMutationComplete, nil
	}
	if registryBound {
		rec, err := e.Registry.Get(ctx, m.Target)
		if err != nil {
			return "", err
		}
		if rec != nil {
			id := fmt.Sprint(rec.Metadata["_chrootctl_mutation_id"])
			installID := fmt.Sprint(rec.Metadata["_chrootctl_install_mutation_id"])
			if id == m.MutationID || installID == m.MutationID {
				if backup != "" && exists(backup) {
					if err := removeIfExists(backup); err != nil {
						if persistErr := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationCleanupDebt, map[string]any{"cleanup_error": err.Error()}); persistErr != nil {
							return "", errors.Join(err, persistErr)
						}
						return registry.FSMutationCleanupDebt, nil
					}
				}
				if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationComplete, map[string]any{"recovered": true}); err != nil {
					return "", err
				}
				return registry.FSMutationComplete, nil
			}
		}
	}
	// Before authoritative commit, roll the filesystem back to the old target.
	if exists(target) && (m.State == registry.FSMutationPromoting || !exists(stage)) {
		if err := removeIfExists(target); err != nil {
			return "", err
		}
	}
	if backup != "" && exists(backup) {
		if exists(target) {
			return "", fmt.Errorf("promotion recovery target still exists while backup is present")
		}
		if err := renameIfPossible(backup, target); err != nil {
			return "", err
		}
	} else if detailBool(m, "had_existing") && !exists(target) {
		return "", fmt.Errorf("promotion recovery expected an original target but backup is missing")
	}
	_ = removeIfExists(stage)
	if err := e.Registry.UpdateFSMutation(ctx, m.MutationID, registry.FSMutationRolledBack, map[string]any{"recovered": true}); err != nil {
		return "", err
	}
	return registry.FSMutationRolledBack, nil
}
