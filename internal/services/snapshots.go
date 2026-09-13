package services

import (
	"archive/tar"
	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/registry"
	"compress/gzip"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type SnapshotService struct{ C *Container }

func (s *SnapshotService) Root() string {
	return filepath.Join(s.C.BaseConfig.ChrootRoot, ".snapshots")
}
func (s *SnapshotService) base(name string) (string, error) {
	return contained(s.Root(), filepath.Join(s.Root(), name), "snapshot chroot directory")
}
func (s *SnapshotService) List(ctx context.Context, name string, limit int) ([]registry.Snapshot, error) {
	return s.C.Registry.ListSnapshots(ctx, name, limit)
}
func safeBase(name, label string) (string, error) {
	name = strings.TrimSpace(name)
	if name == "" || name == "." || name == ".." || filepath.Base(name) != name || strings.ContainsAny(name, "/\\") {
		return "", fmt.Errorf("invalid %s: %s", label, name)
	}
	return name, nil
}
func copyTree(src, dst string) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, e error) error {
		if e != nil {
			return e
		}
		rel, e := filepath.Rel(src, path)
		if e != nil {
			return e
		}
		target := filepath.Join(dst, rel)
		if info.Mode()&os.ModeSymlink != 0 {
			link, e := os.Readlink(path)
			if e != nil {
				return e
			}
			if e = os.MkdirAll(filepath.Dir(target), 0755); e != nil {
				return e
			}
			return os.Symlink(link, target)
		}
		if info.IsDir() {
			return os.MkdirAll(target, info.Mode().Perm())
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		if e = os.MkdirAll(filepath.Dir(target), 0755); e != nil {
			return e
		}
		in, e := os.Open(path)
		if e != nil {
			return e
		}
		defer in.Close()
		out, e := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, info.Mode().Perm())
		if e != nil {
			return e
		}
		_, ce := io.Copy(out, in)
		se := out.Sync()
		cl := out.Close()
		if ce != nil {
			return ce
		}
		if se != nil {
			return se
		}
		return cl
	})
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
func (s *SnapshotService) requireUnmounted(name string) error {
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
	if e = s.requireUnmounted(chrootName); e != nil {
		return model.SnapshotActionResult{}, e
	}
	if name == "" {
		name = "snapshot"
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
	if e = os.MkdirAll(base, 0755); e != nil {
		return model.SnapshotActionResult{}, e
	}
	stage := filepath.Join(base, fmt.Sprintf(".partial-%s-%d", name, time.Now().UnixNano()))
	tx, e := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "snapshot.create", Target: chrootName, Source: source, Destination: target, Scope: "target", Detail: map[string]any{"snapshot": name, "stage": stage}})
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if e = copyTree(source, stage); e != nil {
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
	snap, e := s.C.Registry.AddSnapshot(ctx, registry.SnapshotInput{Name: name, ChrootName: chrootName, Path: target, Kind: "copy", Note: note, SizeBytes: directorySize(target), Metadata: map[string]any{"source_path": source, "_chrootctl_mutation_id": tx.ID}})
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
		return model.SnapshotActionResult{}, e
	}
	target, e := s.source(ctx, chrootName)
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if e = s.requireUnmounted(chrootName); e != nil {
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
	tx, e := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "snapshot.restore", Target: chrootName, Source: source, Destination: target, Scope: "target", Detail: map[string]any{"snapshot": name, "stage": stage, "backup": backup, "had_existing": had}})
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if e = copyTree(source, stage); e != nil {
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
		return model.SnapshotActionResult{}, e
	}
	if archive == "" {
		archive = filepath.Join(filepath.Dir(source), name+".tar.gz")
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
		if e = writeTarGz(source, tmp); e != nil {
			return model.SnapshotActionResult{}, e
		}
		if e = os.Rename(tmp, archive); e != nil {
			return model.SnapshotActionResult{}, e
		}
	}
	a := archive
	return model.SnapshotActionResult{ChrootName: chrootName, SnapshotName: name, Path: source, Action: "export", CreatedAt: snap.CreatedAt, ExportedArchive: &a, NextSteps: []string{"Archive: " + archive}}, nil
}
func writeTarGz(source, target string) error {
	f, e := os.Create(target)
	if e != nil {
		return e
	}
	gz := gzip.NewWriter(f)
	tw := tar.NewWriter(gz)
	base := filepath.Dir(source)
	e = filepath.Walk(source, func(path string, info os.FileInfo, e error) error {
		if e != nil {
			return e
		}
		rel, _ := filepath.Rel(base, path)
		h, e := tar.FileInfoHeader(info, "")
		if e != nil {
			return e
		}
		h.Name = filepath.ToSlash(rel)
		if info.Mode()&os.ModeSymlink != 0 {
			link, e := os.Readlink(path)
			if e != nil {
				return e
			}
			h.Linkname = link
		}
		if e = tw.WriteHeader(h); e != nil {
			return e
		}
		if info.Mode().IsRegular() {
			in, e := os.Open(path)
			if e != nil {
				return e
			}
			_, e = io.Copy(tw, in)
			in.Close()
			return e
		}
		return nil
	})
	ce := tw.Close()
	ge := gz.Close()
	fe := f.Close()
	if e != nil {
		return e
	}
	if ce != nil {
		return ce
	}
	if ge != nil {
		return ge
	}
	return fe
}
