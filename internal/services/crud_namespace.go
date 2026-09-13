package services

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"chrootctl/internal/config"
	"chrootctl/internal/mutation"
	sys "chrootctl/internal/system"
)

type crudMove struct{ From, To string }

// Package-local seams keep destructive-boundary failure injection deterministic
// without changing the production API surface.
var (
	crudRenamePath            = os.Rename
	crudRemoveTree            = os.RemoveAll
	crudSyncDir               = mutation.SyncDir
	crudRewriteChrootOverride = config.RewriteChrootOverride
	crudMountStatus           = func(rt Runtime) []map[string]string { return rt.Controller.Status(true) }
)

type crudNamespacePlan struct {
	Moves       []crudMove
	ConfigPath  string
	HasOverride bool
}

func (s *ChrootService) destructiveTarget(ctx context.Context, name string) (*ResolvedTarget, error) {
	resolved, err := s.C.ResolveTarget(ctx, name, false)
	if err != nil {
		return nil, err
	}
	if resolved == nil {
		return nil, fmt.Errorf("unknown chroot: %s", name)
	}
	st, err := os.Lstat(resolved.RootPath)
	if err != nil {
		return nil, fmt.Errorf("registered chroot path is unavailable: %w", err)
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
		return nil, fmt.Errorf("registered chroot path must be a real directory, not a symlink or special file: %s", resolved.RootPath)
	}
	return resolved, nil
}

func (s *ChrootService) requireFullyUnmounted(resolved *ResolvedTarget) error {
	rt, err := s.C.RuntimeFor(resolved.Record.Name, "")
	if err != nil {
		return err
	}
	for _, row := range crudMountStatus(rt) {
		if strings.EqualFold(row["mounted"], "yes") {
			return fmt.Errorf("chroot must be fully unmounted before identity mutation: %s", resolved.Record.Name)
		}
	}
	return nil
}

func (s *ChrootService) requireNoManagedServiceActivity(name string) error {
	prefix := safeArtifactName(name) + "-"
	entries, err := os.ReadDir(s.C.BaseConfig.ServiceStateDir)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasPrefix(entry.Name(), prefix) {
			continue
		}
		path := filepath.Join(s.C.BaseConfig.ServiceStateDir, entry.Name())
		if strings.HasSuffix(entry.Name(), ".identity.json") {
			id := readIdentity(path)
			if id == nil {
				return fmt.Errorf("unverifiable managed service identity blocks chroot identity mutation: %s", path)
			}
			if sys.ProcessIdentityMatches(*id) {
				return fmt.Errorf("active managed service blocks chroot identity mutation: %s", path)
			}
		}
		if strings.HasSuffix(entry.Name(), ".pid") {
			identity := strings.TrimSuffix(path, ".pid") + ".identity.json"
			if _, statErr := os.Stat(identity); errors.Is(statErr, os.ErrNotExist) {
				return fmt.Errorf("legacy/unverifiable managed service pid blocks chroot identity mutation: %s", path)
			}
		}
	}
	return nil
}

func (s *ChrootService) renameNamespacePlan(oldName, newName string) (crudNamespacePlan, error) {
	plan := crudNamespacePlan{ConfigPath: s.C.ConfigPath}
	if _, err := s.C.ConfigFor(oldName, ""); err != nil {
		return plan, err
	}
	oldOverride := s.C.BaseConfig.ChrootOverrides[oldName]
	if _, exists := s.C.BaseConfig.ChrootOverrides[newName]; exists {
		if _, err := s.C.ConfigFor(newName, ""); err != nil {
			return plan, err
		}
		return plan, fmt.Errorf("destination chroot override already exists: %s", newName)
	}
	plan.HasOverride = len(oldOverride) > 0
	if plan.HasOverride && plan.ConfigPath == "" {
		return plan, fmt.Errorf("cannot migrate persisted chroot override without a config path")
	}

	oldSnap, err := s.C.Snapshots().base(oldName)
	if err != nil {
		return plan, err
	}
	newSnap, err := s.C.Snapshots().base(newName)
	if err != nil {
		return plan, err
	}
	snaps, err := s.C.Registry.ListSnapshots(context.Background(), oldName, 1000000)
	if err != nil {
		return plan, err
	}
	for _, snap := range snaps {
		rel, relErr := filepath.Rel(oldSnap, filepath.Clean(snap.Path))
		if relErr != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return plan, fmt.Errorf("snapshot path escapes chroot snapshot namespace: %s", snap.Path)
		}
		if !exists(snap.Path) {
			return plan, fmt.Errorf("registered snapshot path is missing: %s", snap.Path)
		}
	}
	if exists(oldSnap) {
		plan.Moves = append(plan.Moves, crudMove{oldSnap, newSnap})
	} else if len(snaps) > 0 {
		return plan, fmt.Errorf("snapshot registry rows exist but namespace is missing: %s", oldSnap)
	}
	appendDirectMoves := func(dir, suffix string) error {
		entries, err := os.ReadDir(dir)
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		if err != nil {
			return err
		}
		oldPrefix, newPrefix := safeArtifactName(oldName)+"-", safeArtifactName(newName)+"-"
		for _, ent := range entries {
			if ent.IsDir() || !strings.HasPrefix(ent.Name(), oldPrefix) {
				continue
			}
			if suffix != "" && !strings.HasSuffix(ent.Name(), suffix) {
				continue
			}
			plan.Moves = append(plan.Moves, crudMove{filepath.Join(dir, ent.Name()), filepath.Join(dir, newPrefix+strings.TrimPrefix(ent.Name(), oldPrefix))})
		}
		return nil
	}
	if err := appendDirectMoves(s.C.BaseConfig.ServiceStateDir, ""); err != nil {
		return plan, err
	}
	if err := appendDirectMoves(s.C.BaseConfig.ServiceLogDir, ".log"); err != nil {
		return plan, err
	}
	targetRoot := filepath.Join(s.C.BaseConfig.ServiceStateDir, "targets")
	walkErr := filepath.WalkDir(targetRoot, func(path string, d os.DirEntry, walkErr error) error {
		if walkErr != nil {
			if errors.Is(walkErr, os.ErrNotExist) {
				return nil
			}
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		oldPrefix := safeArtifactName(oldName) + "-"
		if strings.HasPrefix(d.Name(), oldPrefix) && strings.HasSuffix(d.Name(), ".enabled") {
			plan.Moves = append(plan.Moves, crudMove{path, filepath.Join(filepath.Dir(path), safeArtifactName(newName)+"-"+strings.TrimPrefix(d.Name(), oldPrefix))})
		}
		return nil
	})
	if walkErr != nil && !errors.Is(walkErr, os.ErrNotExist) {
		return plan, walkErr
	}
	sort.Slice(plan.Moves, func(i, j int) bool { return plan.Moves[i].From < plan.Moves[j].From })
	for _, m := range plan.Moves {
		if exists(m.To) {
			return plan, fmt.Errorf("destination namespace path already exists: %s", m.To)
		}
	}
	return plan, nil
}

func (s *ChrootService) removeNamespacePlan(name, nonce string) (crudNamespacePlan, error) {
	plan := crudNamespacePlan{ConfigPath: s.C.ConfigPath, HasOverride: len(s.C.BaseConfig.ChrootOverrides[name]) > 0}
	if _, err := s.C.ConfigFor(name, ""); err != nil {
		return plan, err
	}
	if plan.HasOverride && plan.ConfigPath == "" {
		return plan, fmt.Errorf("cannot remove persisted chroot override without a config path")
	}
	oldSnap, err := s.C.Snapshots().base(name)
	if err != nil {
		return plan, err
	}
	snaps, err := s.C.Registry.ListSnapshots(context.Background(), name, 1000000)
	if err != nil {
		return plan, err
	}
	for _, snap := range snaps {
		rel, relErr := filepath.Rel(oldSnap, filepath.Clean(snap.Path))
		if relErr != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return plan, fmt.Errorf("snapshot path escapes chroot snapshot namespace: %s", snap.Path)
		}
		if !exists(snap.Path) {
			return plan, fmt.Errorf("registered snapshot path is missing: %s", snap.Path)
		}
	}
	if exists(oldSnap) {
		plan.Moves = append(plan.Moves, crudMove{oldSnap, oldSnap + ".chrootctl-remove-" + nonce})
	} else if len(snaps) > 0 {
		return plan, fmt.Errorf("snapshot registry rows exist but namespace is missing: %s", oldSnap)
	}
	add := func(path string) {
		plan.Moves = append(plan.Moves, crudMove{path, path + ".chrootctl-remove-" + nonce})
	}
	prefix := safeArtifactName(name) + "-"
	for _, dir := range []string{s.C.BaseConfig.ServiceStateDir, s.C.BaseConfig.ServiceLogDir} {
		entries, readErr := os.ReadDir(dir)
		if errors.Is(readErr, os.ErrNotExist) {
			continue
		}
		if readErr != nil {
			return plan, readErr
		}
		for _, ent := range entries {
			if !ent.IsDir() && strings.HasPrefix(ent.Name(), prefix) {
				add(filepath.Join(dir, ent.Name()))
			}
		}
	}
	walkErr := filepath.WalkDir(filepath.Join(s.C.BaseConfig.ServiceStateDir, "targets"), func(path string, d os.DirEntry, err error) error {
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return nil
			}
			return err
		}
		if !d.IsDir() && strings.HasPrefix(d.Name(), prefix) && strings.HasSuffix(d.Name(), ".enabled") {
			add(path)
		}
		return nil
	})
	if walkErr != nil && !errors.Is(walkErr, os.ErrNotExist) {
		return plan, walkErr
	}
	sort.Slice(plan.Moves, func(i, j int) bool { return plan.Moves[i].From < plan.Moves[j].From })
	for _, m := range plan.Moves {
		if exists(m.To) {
			return plan, fmt.Errorf("remove staging path already exists: %s", m.To)
		}
	}
	return plan, nil
}

func movesDetail(plan crudNamespacePlan) []map[string]any {
	out := make([]map[string]any, 0, len(plan.Moves))
	for _, m := range plan.Moves {
		out = append(out, map[string]any{"from": m.From, "to": m.To})
	}
	return out
}

func applyCrudMoves(moves []crudMove) ([]crudMove, error) {
	done := []crudMove{}
	for _, m := range moves {
		if !exists(m.From) {
			continue
		}
		if err := os.MkdirAll(filepath.Dir(m.To), 0755); err != nil {
			return done, err
		}
		if err := crudRenamePath(m.From, m.To); err != nil {
			return done, err
		}
		done = append(done, m)
		if err := crudSyncDir(filepath.Dir(m.To)); err != nil {
			return done, err
		}
	}
	return done, nil
}
func rollbackCrudMoves(done []crudMove) error {
	var out error
	for i := len(done) - 1; i >= 0; i-- {
		m := done[i]
		if !exists(m.To) {
			continue
		}
		if exists(m.From) {
			out = errors.Join(out, fmt.Errorf("rollback destination occupied: %s", m.From))
			continue
		}
		if err := crudRenamePath(m.To, m.From); err != nil {
			out = errors.Join(out, err)
			continue
		}
		out = errors.Join(out, crudSyncDir(filepath.Dir(m.From)))
	}
	return out
}
func cleanupCrudMoves(moves []crudMove) error {
	var out error
	for _, m := range moves {
		if !exists(m.To) {
			continue
		}
		if err := crudRemoveTree(m.To); err != nil {
			out = errors.Join(out, err)
			continue
		}
		// Removal is not considered durably complete until the directory entry
		// deletion is flushed as well.
		out = errors.Join(out, crudSyncDir(filepath.Dir(m.To)))
	}
	return out
}

func migrateOverride(plan crudNamespacePlan, oldName, newName string, remove bool) error {
	if !plan.HasOverride {
		return nil
	}
	changed, err := crudRewriteChrootOverride(plan.ConfigPath, oldName, newName, remove)
	if err != nil {
		return err
	}
	if !changed {
		return fmt.Errorf("expected persisted chroot override for %s was not found", oldName)
	}
	return nil
}
