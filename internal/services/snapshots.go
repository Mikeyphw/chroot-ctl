package services

import (
	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type SnapshotService struct{ C *Container }

func (s *SnapshotService) Root() string {
	return filepath.Clean(s.C.BaseConfig.SnapshotDir)
}
func (s *SnapshotService) base(name string) (string, error) {
	return contained(s.Root(), filepath.Join(s.Root(), name), "snapshot chroot directory")
}
func (s *SnapshotService) List(ctx context.Context, name string, limit int) ([]registry.Snapshot, error) {
	rows, err := s.C.Registry.ListSnapshots(ctx, name, limit)
	if err != nil {
		return nil, err
	}
	for i := range rows {
		if _, authorityErr := contained(s.Root(), rows[i].Path, "snapshot path"); authorityErr != nil {
			if rows[i].Metadata == nil {
				rows[i].Metadata = map[string]string{}
			}
			rows[i].Metadata["authority_state"] = "legacy_or_external_location"
		}
	}
	return rows, nil
}
func (s *SnapshotService) Preview(ctx context.Context, chrootName, action, name string) (map[string]any, error) {
	action = strings.ToLower(strings.TrimSpace(action))
	if action == "" {
		action = "create"
	}
	if name == "" && action == "create" {
		return map[string]any{"ok": false, "kind": "snapshot.create", "name": chrootName, "snapshot": "", "blocking": []map[string]string{{"code": "missing_snapshot_name", "message": "Snapshot name is required for preview-bound creation."}}, "warnings": []string{}, "confirm": false}, nil
	}
	var err error
	if action == "create" || action == "restore" || action == "export" {
		name, err = safeBase(name, "snapshot name")
		if err != nil {
			return nil, err
		}
	}
	rows, err := s.List(ctx, chrootName, 1000)
	if err != nil {
		return nil, err
	}
	var selected *registry.Snapshot
	for i := range rows {
		if rows[i].Name == name {
			selected = &rows[i]
			break
		}
	}
	blocking := []map[string]string{}
	warnings := []string{}
	switch action {
	case "create":
		if selected != nil {
			blocking = append(blocking, map[string]string{"code": "snapshot_exists", "message": "Snapshot already exists: " + name})
		}
		if err := s.requireUnmounted(ctx, chrootName); err != nil {
			blocking = append(blocking, map[string]string{"code": "target_mounted", "message": err.Error()})
		}
	case "restore":
		if selected == nil {
			blocking = append(blocking, map[string]string{"code": "snapshot_missing", "message": "Snapshot does not exist: " + name})
		} else if selected.Kind != snapshotKindRootfsTarV1 {
			blocking = append(blocking, map[string]string{"code": "legacy_snapshot_format", "message": "Snapshot is not metadata-faithful and cannot be restored safely."})
		}
		if err := s.requireUnmounted(ctx, chrootName); err != nil {
			blocking = append(blocking, map[string]string{"code": "target_mounted", "message": err.Error()})
		}
		warnings = append(warnings, "Restore replaces the current chroot rootfs with the selected metadata-faithful snapshot.")
	case "export":
		if selected == nil {
			blocking = append(blocking, map[string]string{"code": "snapshot_missing", "message": "Snapshot does not exist: " + name})
		} else if selected.Kind != snapshotKindRootfsTarV1 {
			blocking = append(blocking, map[string]string{"code": "legacy_snapshot_format", "message": "Legacy snapshot cannot be exported as a CHR09 bundle."})
		}
	default:
		return nil, fmt.Errorf("unsupported snapshot action: %s", action)
	}
	result := map[string]any{"ok": len(blocking) == 0, "kind": "snapshot." + action, "name": chrootName, "snapshot": name, "existingCount": len(rows), "blocking": blocking, "warnings": warnings, "confirm": action == "restore"}
	if selected != nil {
		result["metadata"] = selected.Metadata
		result["createdAt"] = selected.CreatedAt
		result["snapshotKind"] = selected.Kind
	}
	return result, nil
}
func safeBase(name, label string) (string, error) {
	return validation.SnapshotNameField(name, label)
}

func (s *SnapshotService) source(ctx context.Context, name string) (string, error) {
	resolved, err := s.C.ResolveTarget(ctx, name, false)
	if err != nil {
		return "", err
	}
	if resolved == nil {
		return "", fmt.Errorf("unknown chroot: %s", name)
	}
	return resolved.RootPath, nil
}
func (s *SnapshotService) requireUnmounted(ctx context.Context, name string) error {
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return e
	}
	rows, err := rt.Controller.StatusChecked(true)
	if err != nil {
		return fmt.Errorf("verify chroot mount state: %w", err)
	}
	for _, r := range rows {
		if !strings.EqualFold(r["mounted"], "no") {
			return fmt.Errorf("chroot must be fully and verifiably unmounted: %s (%s)", name, r["mounted"])
		}
	}
	root, err := s.source(ctx, name)
	if err != nil {
		return err
	}
	mounts, err := sys.MountTableDetailed("/proc/mounts")
	if err != nil {
		return fmt.Errorf("verify nested chroot mounts: %w", err)
	}
	root = filepath.Clean(root)
	for _, m := range mounts {
		target := filepath.Clean(m.Target)
		rel, relErr := filepath.Rel(root, target)
		if relErr == nil && rel != "." && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return fmt.Errorf("chroot contains live nested mount %s; unmount it before snapshot", target)
		}
	}
	return nil
}
func (s *SnapshotService) Create(ctx context.Context, chrootName, name, note string) (model.SnapshotActionResult, error) {
	source, e := s.source(ctx, chrootName)
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if !exists(source) {
		return model.SnapshotActionResult{}, fmt.Errorf("missing chroot path: %s", source)
	}
	if e = s.requireUnmounted(ctx, chrootName); e != nil {
		return model.SnapshotActionResult{}, e
	}
	if name == "" {
		name = uniqueSnapshotName("snapshot")
	}
	name, e = safeBase(name, "snapshot name")
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	base, e := s.base(chrootName)
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	target := filepath.Join(base, name)
	if exists(target) {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot already exists: %s", name)
	}
	if s.C.DryRun {
		return model.SnapshotActionResult{ChrootName: chrootName, SnapshotName: name, Path: target, Action: "create", NextSteps: []string{"Review snapshot files: " + target}}, nil
	}
	if e = os.MkdirAll(base, 0o700); e != nil {
		return model.SnapshotActionResult{}, e
	}
	stage := filepath.Join(base, fmt.Sprintf(".partial-%s-%d", name, time.Now().UnixNano()))
	tx, e := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "snapshot.create", Target: chrootName, Source: source, Destination: target, Scope: "target", Detail: map[string]any{"snapshot": name, "stage": stage}})
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if _, e = writeSnapshotPayload(ctx, source, stage, chrootName, name, note); e != nil {
		cleanupErr := os.RemoveAll(stage)
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "error": e.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["cleanup_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	if e = tx.Transition(ctx, registry.FSMutationStaged, map[string]any{"stage": stage}); e != nil {
		cleanupErr := os.RemoveAll(stage)
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "journal_error": e.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["cleanup_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	if e = os.Rename(stage, target); e != nil {
		cleanupErr := os.RemoveAll(stage)
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "rename_error": e.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["cleanup_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	if e = mutation.SyncDir(base); e != nil {
		cleanupErr := os.RemoveAll(target)
		if cleanupErr == nil {
			cleanupErr = mutation.SyncDir(base)
		}
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "sync_error": e.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	if e = tx.Transition(ctx, registry.FSMutationPromoting, map[string]any{"stage": stage}); e != nil {
		cleanupErr := os.RemoveAll(target)
		if cleanupErr == nil {
			cleanupErr = mutation.SyncDir(base)
		}
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "journal_error": e.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	manifest, manifestErr := readSnapshotManifest(target)
	if manifestErr != nil {
		cleanupErr := os.RemoveAll(target)
		if cleanupErr == nil {
			cleanupErr = mutation.SyncDir(base)
		}
		state := registry.FSMutationRolledBack
		detail := map[string]any{"manifest_error": manifestErr.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["cleanup_error"] = cleanupErr.Error()
		}
		journalErr := tx.Transition(context.WithoutCancel(ctx), state, detail)
		return model.SnapshotActionResult{}, errors.Join(fmt.Errorf("snapshot payload manifest verification failed: %w", manifestErr), cleanupErr, journalErr)
	}
	metadata := map[string]any{
		"source_path": source, "_chrootctl_mutation_id": tx.ID, "format_version": manifest.FormatVersion,
		"protected_operation_id": manifest.ProtectedOperationID, "protected_operation_kind": manifest.OperationKind,
		"metadata_contract": strings.Join(manifest.MetadataContract, ","),
	}
	snap, e := s.C.Registry.AddSnapshot(ctx, registry.SnapshotInput{Name: name, ChrootName: chrootName, Path: target, Kind: snapshotKindRootfsTarV1, Note: note, SizeBytes: directorySize(target), Metadata: metadata})
	if e != nil {
		cleanupErr := os.RemoveAll(target)
		if cleanupErr == nil {
			if u := tx.Transition(context.WithoutCancel(ctx), registry.FSMutationRolledBack, map[string]any{"registry_error": e.Error()}); u != nil {
				return model.SnapshotActionResult{}, errors.Join(e, u)
			}
			return model.SnapshotActionResult{}, e
		}
		if u := tx.Transition(context.WithoutCancel(ctx), registry.FSMutationRepairRequired, map[string]any{"registry_error": e.Error(), "cleanup_error": cleanupErr.Error()}); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	if e = tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCommitted, nil); e != nil {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot committed but mutation journal commit failed: %w", e)
	}
	if e = tx.Complete(ctx, nil); e != nil {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot committed but terminal journal persistence failed: %w", e)
	}
	_, _ = s.C.Audit().Record(ctx, "snapshot.create", chrootName, "ok", "Created snapshot "+name, "", map[string]string{"snapshot": name})
	return model.SnapshotActionResult{ChrootName: chrootName, SnapshotName: name, Path: target, Action: "create", CreatedAt: snap.CreatedAt, NextSteps: []string{"Review snapshot files: " + target}}, nil
}

func (s *SnapshotService) Restore(ctx context.Context, chrootName, name string) (model.SnapshotActionResult, error) {
	name, e := safeBase(name, "snapshot name")
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	snap, e := s.C.Registry.GetSnapshotByName(ctx, chrootName, name)
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	source, e := contained(s.Root(), snap.Path, "snapshot source path")
	if e != nil {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot %s is outside the managed snapshot root %s; recreate or migrate it before use: %w", name, s.Root(), e)
	}
	target, e := s.source(ctx, chrootName)
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if e = s.requireUnmounted(ctx, chrootName); e != nil {
		return model.SnapshotActionResult{}, e
	}
	if s.C.DryRun {
		return model.SnapshotActionResult{ChrootName: chrootName, SnapshotName: name, Path: target, Action: "restore", CreatedAt: snap.CreatedAt}, nil
	}
	rootParent := filepath.Dir(target)
	stamp := time.Now().UnixNano()
	stage := filepath.Join(rootParent, fmt.Sprintf(".chrootctl-restore-stage-%s-%d", chrootName, stamp))
	backup := filepath.Join(rootParent, fmt.Sprintf(".chrootctl-restore-backup-%s-%d", chrootName, stamp))
	had := exists(target)
	if snap.Kind != snapshotKindRootfsTarV1 {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot %s uses legacy non-faithful format %q; create a new metadata-faithful snapshot before restore", name, snap.Kind)
	}
	tx, e := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "snapshot.restore", Target: chrootName, Source: source, Destination: target, Scope: "target", Detail: map[string]any{"snapshot": name, "stage": stage, "backup": backup, "had_existing": had}})
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if _, e = extractSnapshotPayload(ctx, source, stage, chrootName, name); e != nil {
		cleanupErr := os.RemoveAll(stage)
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "backup": backup, "error": e.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["cleanup_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	if e = tx.Transition(ctx, registry.FSMutationStaged, map[string]any{"stage": stage, "backup": backup}); e != nil {
		cleanupErr := os.RemoveAll(stage)
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "backup": backup, "journal_error": e.Error()}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["cleanup_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
	}
	if had {
		if e = os.Rename(target, backup); e != nil {
			cleanupErr := os.RemoveAll(stage)
			state := registry.FSMutationRolledBack
			detail := map[string]any{"stage": stage, "backup": backup, "rename_error": e.Error()}
			if cleanupErr != nil {
				state = registry.FSMutationRepairRequired
				detail["cleanup_error"] = cleanupErr.Error()
			}
			if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
				return model.SnapshotActionResult{}, errors.Join(e, cleanupErr, u)
			}
			return model.SnapshotActionResult{}, errors.Join(e, cleanupErr)
		}
		if e = mutation.SyncDir(rootParent); e != nil {
			rollbackErr := os.Rename(backup, target)
			if rollbackErr == nil {
				rollbackErr = mutation.SyncDir(rootParent)
			}
			cleanupErr := os.RemoveAll(stage)
			rollbackErr = errors.Join(rollbackErr, cleanupErr)
			state := registry.FSMutationRolledBack
			detail := map[string]any{"stage": stage, "backup": backup, "sync_error": e.Error()}
			if rollbackErr != nil {
				state = registry.FSMutationRepairRequired
				detail["rollback_error"] = rollbackErr.Error()
			}
			if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
				return model.SnapshotActionResult{}, errors.Join(e, rollbackErr, u)
			}
			return model.SnapshotActionResult{}, errors.Join(e, rollbackErr)
		}
	}
	if e = tx.Transition(ctx, registry.FSMutationPromoting, map[string]any{"stage": stage, "backup": backup, "had_existing": had}); e != nil {
		var rollbackErr error
		if had {
			rollbackErr = os.Rename(backup, target)
			if rollbackErr == nil {
				rollbackErr = mutation.SyncDir(rootParent)
			}
		}
		rollbackErr = errors.Join(rollbackErr, os.RemoveAll(stage))
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "backup": backup, "journal_error": e.Error()}
		if rollbackErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = rollbackErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, rollbackErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, rollbackErr)
	}
	if e = os.Rename(stage, target); e != nil {
		var rollbackErr error
		if had {
			rollbackErr = os.Rename(backup, target)
			if rollbackErr == nil {
				rollbackErr = mutation.SyncDir(rootParent)
			}
		}
		state := registry.FSMutationRolledBack
		detail := map[string]any{"error": e.Error(), "stage": stage, "backup": backup}
		if rollbackErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = rollbackErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, rollbackErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, rollbackErr)
	}
	if e = mutation.SyncDir(rootParent); e != nil {
		rollbackErr := os.RemoveAll(target)
		if had && rollbackErr == nil {
			rollbackErr = os.Rename(backup, target)
		}
		if rollbackErr == nil {
			rollbackErr = mutation.SyncDir(rootParent)
		}
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "backup": backup, "sync_error": e.Error()}
		if rollbackErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = rollbackErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.SnapshotActionResult{}, errors.Join(e, rollbackErr, u)
		}
		return model.SnapshotActionResult{}, errors.Join(e, rollbackErr)
	}
	if e = tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCommitted, map[string]any{"backup": backup, "had_existing": had}); e != nil {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot restore committed but mutation journal commit failed: %w", e)
	}
	if had {
		if e = os.RemoveAll(backup); e != nil {
			if u := tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCleanupDebt, map[string]any{"backup": backup, "cleanup_error": e.Error()}); u != nil {
				return model.SnapshotActionResult{}, errors.Join(e, u)
			}
			return model.SnapshotActionResult{ChrootName: chrootName, SnapshotName: name, Path: target, Action: "restore", CreatedAt: snap.CreatedAt, NextSteps: []string{"Recovery cleanup pending: " + backup}}, nil
		}
	}
	if e = tx.Complete(ctx, map[string]any{"backup": backup}); e != nil {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot restore committed but terminal journal persistence failed: %w", e)
	}
	return model.SnapshotActionResult{ChrootName: chrootName, SnapshotName: name, Path: target, Action: "restore", CreatedAt: snap.CreatedAt, NextSteps: []string{"chrootctl --name " + chrootName + " start --login"}}, nil
}
func (s *SnapshotService) Export(ctx context.Context, chrootName, name, archive string) (model.SnapshotActionResult, error) {
	name, e := safeBase(name, "snapshot name")
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	snap, e := s.C.Registry.GetSnapshotByName(ctx, chrootName, name)
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	source, e := contained(s.Root(), snap.Path, "snapshot source path")
	if e != nil {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot %s is outside the managed snapshot root %s; recreate or migrate it before use: %w", name, s.Root(), e)
	}
	if snap.Kind != snapshotKindRootfsTarV1 {
		return model.SnapshotActionResult{}, fmt.Errorf("snapshot %s uses legacy non-faithful format %q and cannot be exported as a CHR09 snapshot bundle", name, snap.Kind)
	}
	if _, e = readSnapshotManifest(source); e != nil {
		return model.SnapshotActionResult{}, e
	}
	if archive == "" {
		archive = ManagedArchive(chrootName+"-snapshot-"+name, "tar.gz")
	}
	archive, _ = filepath.Abs(archive)
	if rel, _ := filepath.Rel(source, archive); rel == "." || (!strings.HasPrefix(rel, ".."+string(filepath.Separator)) && rel != "..") {
		return model.SnapshotActionResult{}, fmt.Errorf("archive must be outside snapshot source")
	}
	if !s.C.DryRun {
		if e = os.MkdirAll(filepath.Dir(archive), 0755); e != nil {
			return model.SnapshotActionResult{}, e
		}
		tmp := archive + fmt.Sprintf(".partial-%d", time.Now().UnixNano())
		if e = writeSnapshotBundle(source, tmp); e != nil {
			return model.SnapshotActionResult{}, e
		}
		if e = os.Rename(tmp, archive); e != nil {
			return model.SnapshotActionResult{}, e
		}
	}
	a := archive
	return model.SnapshotActionResult{ChrootName: chrootName, SnapshotName: name, Path: source, Action: "export", CreatedAt: snap.CreatedAt, ExportedArchive: &a, NextSteps: []string{"Archive: " + archive}}, nil
}
