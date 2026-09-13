package services

import (
	"archive/tar"
	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	"compress/gzip"
	"context"
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
	for _, r := range rt.Controller.Status(true) {
		if strings.EqualFold(r["mounted"], "yes") {
			return fmt.Errorf("chroot must be fully unmounted: %s", name)
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
	id, e := s.C.Registry.BeginFSMutation(ctx, "snapshot.create", chrootName, source, target, map[string]any{"snapshot": name})
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if e = copyTree(source, stage); e != nil {
		os.RemoveAll(stage)
		_ = s.C.Registry.UpdateFSMutation(ctx, id, "rolled_back", map[string]any{"error": e.Error()})
		return model.SnapshotActionResult{}, e
	}
	_ = s.C.Registry.UpdateFSMutation(ctx, id, "staged", map[string]any{"stage": stage})
	if e = os.Rename(stage, target); e != nil {
		os.RemoveAll(stage)
		_ = s.C.Registry.UpdateFSMutation(ctx, id, "rolled_back", map[string]any{"error": e.Error()})
		return model.SnapshotActionResult{}, e
	}
	snap, e := s.C.Registry.AddSnapshot(ctx, registry.SnapshotInput{Name: name, ChrootName: chrootName, Path: target, Kind: "copy", Note: note, SizeBytes: directorySize(target), Metadata: map[string]any{"source_path": source, "_chrootctl_mutation_id": id}})
	if e != nil {
		os.RemoveAll(target)
		return model.SnapshotActionResult{}, e
	}
	_ = s.C.Registry.UpdateFSMutation(ctx, id, "complete", map[string]any{})
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
	// Restore staging must live beside the authoritative registered root so
	// config-root drift cannot make promotion cross filesystems or target a
	// different chroot parent.
	rootParent := filepath.Dir(target)
	stage := filepath.Join(rootParent, fmt.Sprintf(".chrootctl-restore-stage-%s-%d", chrootName, time.Now().UnixNano()))
	backup := filepath.Join(rootParent, fmt.Sprintf(".chrootctl-restore-backup-%s-%d", chrootName, time.Now().UnixNano()))
	id, e := s.C.Registry.BeginFSMutation(ctx, "snapshot.restore", chrootName, source, target, map[string]any{"snapshot": name})
	if e != nil {
		return model.SnapshotActionResult{}, e
	}
	if e = copyTree(source, stage); e != nil {
		return model.SnapshotActionResult{}, e
	}
	backed := false
	if exists(target) {
		if e = os.Rename(target, backup); e != nil {
			return model.SnapshotActionResult{}, e
		}
		backed = true
	}
	if e = os.Rename(stage, target); e != nil {
		if backed {
			_ = os.Rename(backup, target)
		}
		return model.SnapshotActionResult{}, e
	}
	if backed {
		_ = os.RemoveAll(backup)
	}
	_ = s.C.Registry.UpdateFSMutation(ctx, id, "complete", map[string]any{})
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
