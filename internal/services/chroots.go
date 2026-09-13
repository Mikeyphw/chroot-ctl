package services

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
)

type ChrootService struct{ C *Container }

var crudRegistryRenameIdentity = func(r *registry.Registry, ctx context.Context, oldName, newName string, newPath *string, oldSnapRoot, newSnapRoot string) error {
	return r.RenameIdentity(ctx, oldName, newName, newPath, oldSnapRoot, newSnapRoot)
}
var crudRegistryDelete = func(r *registry.Registry, ctx context.Context, name string) error { return r.Delete(ctx, name) }
var crudUnmountTarget = func(ctx context.Context, rt Runtime) model.OperationResult { return rt.Controller.Unmount(ctx) }

func chrootModel(r registry.Chroot) model.ChrootRecord {
	return model.ChrootRecord{Name: r.Name, Distro: r.Distro, Path: r.Path, Arch: ptrText(r.Arch), ReleaseName: ptrText(r.ReleaseName), Version: ptrText(r.Version), Phase: r.Phase, Installed: r.Installed, CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt, Metadata: stringMetadata(r.Metadata)}
}
func stringMetadata(m map[string]any) map[string]string {
	out := map[string]string{}
	for k, v := range m {
		out[k] = fmt.Sprint(v)
	}
	return out
}
func (s *ChrootService) List(ctx context.Context) ([]model.ChrootRecord, error) {
	rows, e := s.C.Registry.List(ctx)
	out := make([]model.ChrootRecord, 0, len(rows))
	for _, r := range rows {
		out = append(out, chrootModel(r))
	}
	return out, e
}
func (s *ChrootService) Get(ctx context.Context, name string) (model.ChrootDetails, error) {
	name, e := validation.ChrootNameField(name, "chroot name")
	if e != nil {
		return model.ChrootDetails{}, e
	}
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil {
		return model.ChrootDetails{}, e
	}
	if r == nil {
		return model.ChrootDetails{}, fmt.Errorf("unknown chroot: %s", name)
	}
	cfg, e := s.C.ConfigFor(name, "")
	if e != nil {
		return model.ChrootDetails{}, e
	}
	mounts := []string{}
	for _, m := range cfg.MediaMounts {
		if m.Enabled {
			mounts = append(mounts, m.Source+" -> "+m.Target)
		}
	}
	for _, m := range cfg.ExtraBindMounts {
		if m.Enabled {
			mounts = append(mounts, m.Source+" -> "+m.Target)
		}
	}
	extra := "none"
	if len(cfg.ExtraPackages) > 0 {
		extra = strings.Join(cfg.ExtraPackages, ",")
	}
	return model.ChrootDetails{Name: r.Name, Distro: r.Distro, Path: r.Path, ReleaseName: ptrText(r.ReleaseName), Version: ptrText(r.Version), Phase: r.Phase, Installed: r.Installed, Arch: ptrText(r.Arch), CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt, ConfiguredMounts: strings.Join(mounts, ", "), ExtraPackages: extra, Locale: cfg.Locale, Metadata: stringMetadata(r.Metadata)}, nil
}
func (s *ChrootService) requireRunnable(ctx context.Context, name string) (*registry.Chroot, Runtime, string, error) {
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil {
		return nil, Runtime{}, "", e
	}
	if r == nil {
		return nil, Runtime{}, "", fmt.Errorf("unknown chroot: %s", name)
	}
	if !r.Installed {
		return nil, Runtime{}, "", fmt.Errorf("chroot is not installed and cannot be started: %s", name)
	}
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return nil, Runtime{}, "", e
	}
	root := r.Path
	if root == "" {
		root = rt.Config.ChrootBase()
	}
	root, e = contained(rt.Config.ChrootRoot, root, "registered chroot path")
	if e != nil {
		return nil, Runtime{}, "", e
	}
	if st, e := os.Stat(root); e != nil || !st.IsDir() {
		return nil, Runtime{}, "", fmt.Errorf("registered chroot path is missing or not a directory: %s", root)
	}
	return r, rt, root, nil
}
func (s *ChrootService) Start(ctx context.Context, name string) (model.SessionActionResult, error) {
	_, rt, _, e := s.requireRunnable(ctx, name)
	if e != nil {
		return model.SessionActionResult{}, e
	}
	e = rt.Controller.Prepare(ctx, false)
	code := 0
	if e != nil {
		code = 1
	}
	return model.SessionActionResult{Action: "start", Target: name, ExitCode: code, NextSteps: []string{"chrootctl --name " + name + " logs --all"}}, e
}
func (s *ChrootService) Restart(ctx context.Context, name string) (model.SessionActionResult, error) {
	_, rt, _, e := s.requireRunnable(ctx, name)
	if e != nil {
		return model.SessionActionResult{}, e
	}
	un := crudUnmountTarget(ctx, rt)
	if un.Failed > 0 {
		return model.SessionActionResult{Action: "restart", Target: name, ExitCode: 1, NextSteps: []string{"chrootctl --name " + name + " doctor"}}, fmt.Errorf("failed to unmount %d path(s): %s", un.Failed, strings.Join(un.Errors, "; "))
	}
	e = rt.Controller.Prepare(ctx, false)
	code := 0
	if e != nil {
		code = 1
	}
	return model.SessionActionResult{Action: "restart", Target: name, ExitCode: code, NextSteps: []string{"chrootctl --name " + name + " logs --all"}}, e
}
func (s *ChrootService) Remove(ctx context.Context, name string) (model.ChrootRemovalResult, error) {
	resolved, e := s.destructiveTarget(ctx, name)
	if e != nil {
		return model.ChrootRemovalResult{}, e
	}
	if e = s.requireNoManagedServiceActivity(name); e != nil {
		return model.ChrootRemovalResult{}, e
	}
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return model.ChrootRemovalResult{}, e
	}
	un := crudUnmountTarget(ctx, rt)
	if un.Failed > 0 {
		return model.ChrootRemovalResult{Name: name, UnmountedSuccess: un.Success, UnmountedFailed: un.Failed}, fmt.Errorf("failed to unmount chroot")
	}
	if e = s.requireFullyUnmounted(resolved); e != nil {
		return model.ChrootRemovalResult{}, e
	}
	root := resolved.RootPath
	if s.C.DryRun {
		return model.ChrootRemovalResult{Name: name, Removed: true, UnmountedSuccess: un.Success, UnmountedFailed: un.Failed}, nil
	}
	nonce := fmt.Sprintf("%d", time.Now().UnixNano())
	tomb := filepath.Join(filepath.Dir(root), "."+filepath.Base(root)+".chrootctl-remove-"+nonce)
	plan, e := s.removeNamespacePlan(name, nonce)
	if e != nil {
		return model.ChrootRemovalResult{}, e
	}
	detail := map[string]any{"tombstone": tomb, "namespace_moves": movesDetail(plan), "config_path": plan.ConfigPath, "config_override": plan.HasOverride}
	tx, e := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "chroot-remove", Target: name, Source: root, Destination: tomb, Scope: "target", Detail: detail})
	if e != nil {
		return model.ChrootRemovalResult{}, e
	}
	if e = tx.Transition(ctx, registry.FSMutationStaged, detail); e != nil {
		return model.ChrootRemovalResult{}, e
	}
	if e = crudRenamePath(root, tomb); e != nil {
		return model.ChrootRemovalResult{}, tx.Fail(ctx, e, detail)
	}
	if e = crudSyncDir(filepath.Dir(root)); e != nil {
		return model.ChrootRemovalResult{}, s.rollbackRemove(ctx, tx, root, tomb, nil, e, detail)
	}
	done, e := applyCrudMoves(plan.Moves)
	if e != nil {
		return model.ChrootRemovalResult{}, s.rollbackRemove(ctx, tx, root, tomb, done, e, detail)
	}
	if e = tx.Transition(ctx, registry.FSMutationPromoting, detail); e != nil {
		return model.ChrootRemovalResult{}, s.rollbackRemove(ctx, tx, root, tomb, done, e, detail)
	}
	if e = crudRegistryDelete(s.C.Registry, ctx, name); e != nil {
		return model.ChrootRemovalResult{}, s.rollbackRemove(ctx, tx, root, tomb, done, e, detail)
	}
	if e = tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCommitted, detail); e != nil {
		return model.ChrootRemovalResult{}, fmt.Errorf("chroot registry deletion committed but mutation journal commit failed: %w", e)
	}
	commitCtx := context.WithoutCancel(ctx)
	cleanupErr := crudRemoveTree(tomb)
	if cleanupErr == nil {
		cleanupErr = crudSyncDir(filepath.Dir(tomb))
	}
	cleanupErr = errors.Join(cleanupErr, cleanupCrudMoves(plan.Moves))
	if plan.HasOverride {
		if overrideErr := migrateOverride(plan, name, "", true); overrideErr != nil {
			cleanupErr = errors.Join(cleanupErr, overrideErr)
		} else {
			delete(s.C.BaseConfig.ChrootOverrides, name)
		}
	}
	if cleanupErr != nil {
		if u := tx.Transition(commitCtx, registry.FSMutationCleanupDebt, map[string]any{"cleanup_error": cleanupErr.Error()}); u != nil {
			return model.ChrootRemovalResult{}, errors.Join(cleanupErr, u)
		}
		return model.ChrootRemovalResult{Name: name, Removed: true, UnmountedSuccess: un.Success, UnmountedFailed: un.Failed}, nil
	}
	if e = tx.Complete(commitCtx, detail); e != nil {
		return model.ChrootRemovalResult{}, fmt.Errorf("chroot removal committed but terminal journal persistence failed: %w", e)
	}
	return model.ChrootRemovalResult{Name: name, Removed: true, UnmountedSuccess: un.Success, UnmountedFailed: un.Failed}, nil
}

func (s *ChrootService) rollbackRemove(ctx context.Context, tx *mutation.Tx, root, tomb string, done []crudMove, cause error, detail map[string]any) error {
	rb := rollbackCrudMoves(done)
	if exists(tomb) {
		if exists(root) {
			rb = errors.Join(rb, fmt.Errorf("remove rollback found both root and tombstone: %s / %s", root, tomb))
		} else if e := crudRenamePath(tomb, root); e != nil {
			rb = errors.Join(rb, e)
		} else {
			rb = errors.Join(rb, crudSyncDir(filepath.Dir(root)))
		}
	}
	state := registry.FSMutationRolledBack
	patch := map[string]any{"rollback_cause": cause.Error()}
	if rb != nil {
		state = registry.FSMutationRepairRequired
		patch["rollback_error"] = rb.Error()
	}
	if u := tx.Transition(context.WithoutCancel(ctx), state, patch); u != nil {
		return errors.Join(cause, rb, u)
	}
	return errors.Join(cause, rb)
}

func (s *ChrootService) Rename(ctx context.Context, oldName, newName string) (model.ChrootRenameResult, error) {
	oldName, e := validation.ChrootNameField(oldName, "chroot name")
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	newName, e = validation.ChrootNameField(newName, "new chroot name")
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	if x, err := s.C.Registry.Get(ctx, newName); err != nil {
		return model.ChrootRenameResult{}, err
	} else if x != nil {
		return model.ChrootRenameResult{}, fmt.Errorf("chroot already exists: %s", newName)
	}
	resolved, e := s.destructiveTarget(ctx, oldName)
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	if e = s.requireFullyUnmounted(resolved); e != nil {
		return model.ChrootRenameResult{}, e
	}
	if e = s.requireNoManagedServiceActivity(oldName); e != nil {
		return model.ChrootRenameResult{}, e
	}
	plan, e := s.renameNamespacePlan(oldName, newName)
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	oldPath := resolved.RootPath
	newPath := filepath.Join(filepath.Dir(oldPath), newName)
	if oldPath == newPath {
		return model.ChrootRenameResult{OldName: oldName, NewName: newName, Renamed: true}, nil
	}
	if exists(newPath) {
		return model.ChrootRenameResult{}, fmt.Errorf("target chroot path already exists: %s", newPath)
	}
	oldSnap, e := s.C.Snapshots().base(oldName)
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	newSnap, e := s.C.Snapshots().base(newName)
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	if s.C.DryRun {
		return model.ChrootRenameResult{OldName: oldName, NewName: newName, Renamed: true}, nil
	}
	detail := map[string]any{"new_name": newName, "namespace_moves": movesDetail(plan), "config_path": plan.ConfigPath, "config_override": plan.HasOverride, "snapshot_old_root": oldSnap, "snapshot_new_root": newSnap}
	tx, e := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "chroot-rename", Target: oldName, Source: oldPath, Destination: newPath, Scope: "target", Detail: detail})
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	if e = tx.Transition(ctx, registry.FSMutationStaged, detail); e != nil {
		return model.ChrootRenameResult{}, e
	}
	if e = crudRenamePath(oldPath, newPath); e != nil {
		return model.ChrootRenameResult{}, tx.Fail(ctx, e, detail)
	}
	if e = crudSyncDir(filepath.Dir(oldPath)); e != nil {
		return model.ChrootRenameResult{}, s.rollbackRename(ctx, tx, plan, oldName, newName, oldPath, newPath, nil, false, e)
	}
	done, e := applyCrudMoves(plan.Moves)
	if e != nil {
		return model.ChrootRenameResult{}, s.rollbackRename(ctx, tx, plan, oldName, newName, oldPath, newPath, done, false, e)
	}
	if e = tx.Transition(ctx, registry.FSMutationPromoting, detail); e != nil {
		return model.ChrootRenameResult{}, s.rollbackRename(ctx, tx, plan, oldName, newName, oldPath, newPath, done, false, e)
	}
	// Persist the configuration identity before committing the registry rename.
	// A crash here is recoverable because the old registry owner remains
	// authoritative and recovery reverses this override move.
	configMigrated := false
	if plan.HasOverride {
		if e = migrateOverride(plan, oldName, newName, false); e != nil {
			return model.ChrootRenameResult{}, s.rollbackRename(ctx, tx, plan, oldName, newName, oldPath, newPath, done, false, e)
		}
		override := s.C.BaseConfig.ChrootOverrides[oldName]
		delete(s.C.BaseConfig.ChrootOverrides, oldName)
		s.C.BaseConfig.ChrootOverrides[newName] = override
		configMigrated = true
	}
	if e = crudRegistryRenameIdentity(s.C.Registry, ctx, oldName, newName, &newPath, oldSnap, newSnap); e != nil {
		return model.ChrootRenameResult{}, s.rollbackRename(ctx, tx, plan, oldName, newName, oldPath, newPath, done, configMigrated, e)
	}
	if e = tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCommitted, detail); e != nil {
		return model.ChrootRenameResult{}, fmt.Errorf("chroot rename committed but mutation journal commit failed: %w", e)
	}
	commitCtx := context.WithoutCancel(ctx)
	if e = tx.Complete(commitCtx, detail); e != nil {
		return model.ChrootRenameResult{}, fmt.Errorf("chroot rename committed but terminal journal persistence failed: %w", e)
	}
	return model.ChrootRenameResult{OldName: oldName, NewName: newName, Renamed: true}, nil
}

func (s *ChrootService) rollbackRename(ctx context.Context, tx *mutation.Tx, plan crudNamespacePlan, oldName, newName, oldPath, newPath string, done []crudMove, configMigrated bool, cause error) error {
	rb := rollbackCrudMoves(done)
	if configMigrated {
		changed, configErr := crudRewriteChrootOverride(plan.ConfigPath, newName, oldName, false)
		if configErr != nil {
			rb = errors.Join(rb, configErr)
		} else if !changed {
			rb = errors.Join(rb, fmt.Errorf("rollback expected persisted chroot override for %s", newName))
		} else {
			override := s.C.BaseConfig.ChrootOverrides[newName]
			delete(s.C.BaseConfig.ChrootOverrides, newName)
			s.C.BaseConfig.ChrootOverrides[oldName] = override
		}
	}
	if exists(newPath) {
		if exists(oldPath) {
			rb = errors.Join(rb, fmt.Errorf("rename rollback found both old and new root paths: %s / %s", oldPath, newPath))
		} else if e := crudRenamePath(newPath, oldPath); e != nil {
			rb = errors.Join(rb, e)
		} else {
			rb = errors.Join(rb, crudSyncDir(filepath.Dir(oldPath)))
		}
	}
	state := registry.FSMutationRolledBack
	patch := map[string]any{"rollback_cause": cause.Error()}
	if rb != nil {
		state = registry.FSMutationRepairRequired
		patch["rollback_error"] = rb.Error()
	}
	if u := tx.Transition(context.WithoutCancel(ctx), state, patch); u != nil {
		return errors.Join(cause, rb, u)
	}
	return errors.Join(cause, rb)
}

func (s *ChrootService) StorageStatus(ctx context.Context, name string) (map[string]any, error) {
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil {
		return nil, e
	}
	if r == nil {
		return nil, fmt.Errorf("unknown chroot: %s", name)
	}
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return nil, e
	}
	root, e := contained(rt.Config.ChrootRoot, r.Path, "registered chroot path")
	if e != nil {
		return nil, e
	}
	cache := filepath.Join(root, "var", "cache")
	total, used, free := diskUsage(root)
	rows, mountErr := rt.Controller.StatusChecked(true)
	if mountErr != nil {
		return nil, fmt.Errorf("read storage mount state: %w", mountErr)
	}
	mounted, mismatched := 0, 0
	for _, x := range rows {
		switch strings.ToLower(x["mounted"]) {
		case "yes":
			mounted++
		case "mismatch":
			mismatched++
		}
	}
	mountState := "not-mounted"
	if mismatched > 0 {
		mountState = "mismatch"
	} else if mounted > 0 {
		mountState = "mounted"
	}
	snapshotDirectory, snapshotErr := s.C.Snapshots().base(name)
	if snapshotErr != nil {
		return nil, snapshotErr
	}
	return map[string]any{"name": name, "rootfsPath": root, "rootfsExists": exists(root), "rootfsBytes": directorySize(root), "cachePath": cache, "cacheExists": exists(cache), "cacheBytes": directorySize(cache), "freeBytes": free, "usedBytes": used, "totalBytes": total, "mountState": mountState, "mountedCount": mounted, "mismatchedMountCount": mismatched, "mountCount": len(rows), "snapshotDirectory": snapshotDirectory}, nil
}
func (s *ChrootService) DeletePreview(ctx context.Context, name string) (map[string]any, error) {
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil || r == nil {
		if e == nil {
			e = fmt.Errorf("unknown chroot: %s", name)
		}
		return nil, e
	}
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return nil, e
	}
	root, e := contained(rt.Config.ChrootRoot, r.Path, "registered chroot path")
	if e != nil {
		return nil, e
	}
	mountRows, e := rt.Controller.StatusChecked(true)
	if e != nil {
		return nil, fmt.Errorf("delete preview mount status: %w", e)
	}
	mounted := 0
	mismatched := 0
	for _, row := range mountRows {
		if row["mounted"] == "yes" {
			mounted++
		} else if row["mounted"] == "mismatch" {
			mismatched++
		}
	}
	serviceRows, e := s.C.Services().List(ctx)
	if e != nil {
		return nil, fmt.Errorf("delete preview service status: %w", e)
	}
	activeServices := []string{}
	attentionServices := []string{}
	for _, row := range serviceRows {
		if row["chroot"] != name {
			continue
		}
		switch strings.ToLower(row["status"]) {
		case "running":
			activeServices = append(activeServices, row["service"])
		case "stale", "failed":
			attentionServices = append(attentionServices, row["service"])
		}
	}
	snaps, e := s.C.Snapshots().List(ctx, name, 10000)
	if e != nil {
		return nil, e
	}
	snapshotBytes := int64(0)
	for _, snap := range snaps {
		snapshotBytes += directorySize(snap.Path)
	}
	blocking := []map[string]string{}
	if mounted > 0 || mismatched > 0 {
		blocking = append(blocking, map[string]string{"code": "target_mounted", "message": fmt.Sprintf("%d mount(s) active and %d mismatched; unmount before removal", mounted, mismatched)})
	}
	if len(activeServices) > 0 || len(attentionServices) > 0 {
		blocking = append(blocking, map[string]string{"code": "service_state_active", "message": "stop/reconcile service state before removal: " + strings.Join(append(activeServices, attentionServices...), ",")})
	}
	_, hasOverride := s.C.BaseConfig.ChrootOverrides[name]
	return map[string]any{"ok": len(blocking) == 0, "kind": "delete", "name": name, "path": root, "reclaim_bytes": directorySize(root), "mounted_count": mounted, "mount_count": len(mountRows), "mount_mismatch_count": mismatched, "running_services": activeServices, "service_attention": attentionServices, "snapshot_count": len(snaps), "snapshot_bytes": snapshotBytes, "config_override": hasOverride, "blocking": blocking}, nil
}
func (s *ChrootService) ExportPreview(ctx context.Context, name, archive string) (map[string]any, error) {
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil || r == nil {
		if e == nil {
			e = fmt.Errorf("unknown chroot: %s", name)
		}
		return nil, e
	}
	rt, _ := s.C.RuntimeFor(name, "")
	source, e := contained(rt.Config.ChrootRoot, r.Path, "registered chroot path")
	if e != nil {
		return nil, e
	}
	blocking := []map[string]string{}
	if archive == "" {
		archive = ManagedArchive(name, "tar.zst")
	}
	archive, _ = filepath.Abs(archive)
	if managedRoot, err := EnsureManagedTransferRoot(); err != nil {
		blocking = append(blocking, map[string]string{"code": "managed_root_unavailable", "message": err.Error()})
	} else if managedArchive, err := contained(managedRoot, archive, "managed transfer artifact"); err != nil {
		blocking = append(blocking, map[string]string{"code": "archive_outside_managed_root", "message": err.Error()})
	} else {
		archive = managedArchive
	}
	if rel, _ := filepath.Rel(source, archive); rel != "" && rel != "." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && rel != ".." {
		blocking = append(blocking, map[string]string{"code": "archive_inside_source", "message": "archive path must be outside the chroot source"})
	}
	size := directorySize(source)
	_, _, free := diskUsage(filepath.Dir(archive))
	if free < uint64(size) {
		blocking = append(blocking, map[string]string{"code": "insufficient_space", "message": "The export destination does not have enough free space."})
	}
	return map[string]any{"ok": len(blocking) == 0, "kind": "export", "name": name, "archive": archive, "size_bytes": size, "required_bytes": size, "free_bytes": free, "enough_space": free >= uint64(size), "blocking": blocking, "warnings": []any{}}, nil
}
func (s *ChrootService) ValidateImport(ctx context.Context, name string) (map[string]any, error) {
	name, err := validation.ChrootNameField(name, "imported chroot name")
	if err != nil {
		return nil, err
	}
	r, err := s.C.Registry.Get(ctx, name)
	if err != nil {
		return nil, err
	}
	if r == nil {
		return nil, fmt.Errorf("unknown chroot: %s", name)
	}
	checks := []map[string]string{}
	blocking := []map[string]string{}
	add := func(id, result, detail string) {
		row := map[string]string{"id": id, "result": result, "detail": detail}
		checks = append(checks, row)
		if result == "FAIL" {
			blocking = append(blocking, row)
		}
	}
	root, pathErr := validateRegisteredTargetPath(s.C.BaseConfig.ChrootRoot, name, r.Path)
	if pathErr != nil {
		add("registry.path", "FAIL", pathErr.Error())
	} else if root, pathErr = contained(s.C.BaseConfig.ChrootRoot, root, "registered chroot path"); pathErr != nil {
		add("registry.path", "FAIL", pathErr.Error())
	} else {
		add("registry.path", "PASS", root)
		st, statErr := os.Lstat(root)
		switch {
		case statErr != nil:
			add("root.exists", "FAIL", statErr.Error())
		case st.Mode()&os.ModeSymlink != 0:
			add("root.symlink", "FAIL", "registered root must not be a symlink")
		case !st.IsDir():
			add("root.directory", "FAIL", "registered root must be a directory")
		default:
			add("root.directory", "PASS", "registered root is a real directory")
			if st.Mode().Perm()&0o002 != 0 {
				add("root.mode", "FAIL", fmt.Sprintf("registered root is world-writable: %s", st.Mode().Perm()))
			} else {
				add("root.mode", "PASS", st.Mode().Perm().String())
			}
			if _, err := os.Stat(filepath.Join(root, "etc")); err != nil {
				add("root.etc", "WARN", "rootfs has no etc directory yet")
			} else {
				add("root.etc", "PASS", "etc directory exists")
			}
			if _, err := os.Stat(filepath.Join(root, "bin")); err != nil {
				if _, usrErr := os.Stat(filepath.Join(root, "usr", "bin")); usrErr != nil {
					add("root.bin", "WARN", "rootfs has no bin or usr/bin directory yet")
				} else {
					add("root.bin", "PASS", "usr/bin directory exists")
				}
			} else {
				add("root.bin", "PASS", "bin directory exists")
			}
		}
	}
	switch r.Distro {
	case "ubuntu", "arch":
		add("registry.distro", "PASS", r.Distro)
	default:
		add("registry.distro", "FAIL", "unsupported distro: "+r.Distro)
	}
	arch := ptrText(r.Arch)
	if arch == "" {
		arch = s.C.BaseConfig.TargetArch
	}
	switch arch {
	case "", "arm64", "amd64":
		add("registry.arch", "PASS", arch)
	default:
		add("registry.arch", "FAIL", "unsupported architecture: "+arch)
	}
	validPhase := map[string]bool{"registered": true, "extract": true, "bootstrap": true, "desktop": true, "finalize": true, "ready": true}
	if !validPhase[r.Phase] {
		add("registry.phase", "FAIL", "unsupported phase: "+r.Phase)
	} else {
		add("registry.phase", "PASS", r.Phase)
	}
	if r.Installed && r.Phase != "finalize" && r.Phase != "ready" {
		add("registry.installed_phase", "FAIL", "installed chroot must be finalize or ready")
	} else {
		add("registry.installed_phase", "PASS", fmt.Sprintf("installed=%v phase=%s", r.Installed, r.Phase))
	}
	if _, ok := r.Metadata["_chrootctl_mutation_id"]; ok {
		add("registry.import_marker", "PASS", "mutation marker recorded")
	} else {
		add("registry.import_marker", "WARN", "no import mutation marker recorded")
	}
	ok := len(blocking) == 0
	return map[string]any{"name": name, "path": r.Path, "validation_ok": ok, "checks": checks, "blocking": blocking}, nil
}

func (s *ChrootService) PackageDiff(ctx context.Context, left, right string) (model.PackageDiffResult, error) {
	a, e := s.packageInventory(ctx, left)
	if e != nil {
		return model.PackageDiffResult{}, e
	}
	b, e := s.packageInventory(ctx, right)
	if e != nil {
		return model.PackageDiffResult{}, e
	}
	onlyA, onlyB := []string{}, []string{}
	common := 0
	for x := range a {
		if b[x] {
			common++
		} else {
			onlyA = append(onlyA, x)
		}
	}
	for x := range b {
		if !a[x] {
			onlyB = append(onlyB, x)
		}
	}
	sort.Strings(onlyA)
	sort.Strings(onlyB)
	if len(onlyA) > 250 {
		onlyA = onlyA[:250]
	}
	if len(onlyB) > 250 {
		onlyB = onlyB[:250]
	}
	return model.PackageDiffResult{Left: left, Right: right, LeftCount: len(a), RightCount: len(b), OnlyLeft: onlyA, OnlyRight: onlyB, CommonCount: common}, nil
}
func (s *ChrootService) PackageInventory(ctx context.Context, name string, limit int) (model.PackageInventoryResult, error) {
	items, err := s.packageInventory(ctx, name)
	if err != nil {
		return model.PackageInventoryResult{}, err
	}
	out := make([]string, 0, len(items))
	for item := range items {
		out = append(out, item)
	}
	sort.Strings(out)
	total := len(out)
	truncated := false
	if limit > 0 && len(out) > limit {
		out = out[:limit]
		truncated = true
	}
	return model.PackageInventoryResult{Name: name, Count: total, Packages: out, Limit: limit, Truncated: truncated}, nil
}

func (s *ChrootService) packageInventory(ctx context.Context, name string) (map[string]bool, error) {
	r, rt, root, e := s.requireRunnable(ctx, name)
	if e != nil {
		return nil, e
	}
	arch := rt.Config.TargetArch
	if r.Arch != nil && *r.Arch != "" {
		arch = *r.Arch
	}
	if arch != "" && arch != sys.HostArch() && !sys.CanExecuteForeignArch(arch) {
		return nil, fmt.Errorf("package inventory for %s requires foreign-architecture execution support for %s", name, arch)
	}
	var cmd string
	if r.Distro == "ubuntu" {
		cmd = "dpkg-query -W -f='${binary:Package}\\n'"
	} else {
		cmd = "pacman -Qq"
	}
	res, e := rt.Runner.Run(ctx, []string{"busybox", "chroot", root, "/bin/bash", "-lc", cmd}, sys.RunOptions{AllowFailure: true, ChrootEnv: true})
	if e != nil {
		return nil, e
	}
	if res.ReturnCode != 0 {
		return nil, fmt.Errorf("package inventory failed: %s", strings.TrimSpace(res.Stderr))
	}
	out := map[string]bool{}
	scan := bufio.NewScanner(strings.NewReader(res.Stdout))
	for scan.Scan() {
		x := strings.TrimSpace(scan.Text())
		if x != "" {
			out[x] = true
		}
	}
	return out, scan.Err()
}
