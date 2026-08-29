package services

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
)

type ChrootService struct{ C *Container }

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
	un := rt.Controller.Unmount(ctx)
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
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil {
		return model.ChrootRemovalResult{}, e
	}
	if r == nil {
		return model.ChrootRemovalResult{}, fmt.Errorf("unknown chroot: %s", name)
	}
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return model.ChrootRemovalResult{}, e
	}
	un := rt.Controller.Unmount(ctx)
	if un.Failed > 0 {
		return model.ChrootRemovalResult{Name: name, UnmountedSuccess: un.Success, UnmountedFailed: un.Failed}, fmt.Errorf("failed to unmount chroot")
	}
	root, e := contained(rt.Config.ChrootRoot, r.Path, "registered chroot path")
	if e != nil {
		return model.ChrootRemovalResult{}, e
	}
	if !s.C.DryRun {
		mutation, e := s.C.Registry.BeginFSMutation(ctx, "chroot-remove", name, root, "", map[string]any{})
		if e != nil {
			return model.ChrootRemovalResult{}, e
		}
		if e = os.RemoveAll(root); e != nil {
			_ = s.C.Registry.UpdateFSMutation(ctx, mutation, "failed", map[string]any{"error": e.Error()})
			return model.ChrootRemovalResult{}, e
		}
		_ = s.C.Registry.UpdateFSMutation(ctx, mutation, "completed", map[string]any{})
	}
	if e = s.C.Registry.Delete(ctx, name); e != nil {
		return model.ChrootRemovalResult{}, e
	}
	return model.ChrootRemovalResult{Name: name, Removed: true, UnmountedSuccess: un.Success, UnmountedFailed: un.Failed}, nil
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
	if x, _ := s.C.Registry.Get(ctx, newName); x != nil {
		return model.ChrootRenameResult{}, fmt.Errorf("chroot already exists: %s", newName)
	}
	r, e := s.C.Registry.Get(ctx, oldName)
	if e != nil || r == nil {
		if e == nil {
			e = fmt.Errorf("unknown chroot: %s", oldName)
		}
		return model.ChrootRenameResult{}, e
	}
	oldCfg, _ := s.C.ConfigFor(oldName, "")
	newCfg, _ := s.C.ConfigFor(newName, "")
	oldPath, e := contained(oldCfg.ChrootRoot, r.Path, "registered chroot path")
	if e != nil {
		return model.ChrootRenameResult{}, e
	}
	newPath := newCfg.ChrootBase()
	if oldPath != newPath && !s.C.DryRun {
		if exists(newPath) {
			return model.ChrootRenameResult{}, fmt.Errorf("target chroot path already exists: %s", newPath)
		}
		id, e := s.C.Registry.BeginFSMutation(ctx, "chroot-rename", oldName, oldPath, newPath, map[string]any{"new_name": newName})
		if e != nil {
			return model.ChrootRenameResult{}, e
		}
		if e = os.Rename(oldPath, newPath); e != nil {
			_ = s.C.Registry.UpdateFSMutation(ctx, id, "failed", map[string]any{"error": e.Error()})
			return model.ChrootRenameResult{}, e
		}
		_ = s.C.Registry.UpdateFSMutation(ctx, id, "completed", map[string]any{})
	}
	if e = s.C.Registry.Rename(ctx, oldName, newName, &newPath); e != nil {
		return model.ChrootRenameResult{}, e
	}
	return model.ChrootRenameResult{OldName: oldName, NewName: newName, Renamed: true}, nil
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
	rows := rt.Controller.Status(true)
	mounted := 0
	for _, x := range rows {
		if strings.EqualFold(x["mounted"], "yes") {
			mounted++
		}
	}
	return map[string]any{"name": name, "rootfsPath": root, "rootfsExists": exists(root), "rootfsBytes": directorySize(root), "cachePath": cache, "cacheExists": exists(cache), "cacheBytes": directorySize(cache), "freeBytes": free, "usedBytes": used, "totalBytes": total, "mountState": map[bool]string{true: "mounted", false: "not-mounted"}[mounted > 0], "mountedCount": mounted, "mountCount": len(rows), "snapshotDirectory": rt.Config.SnapshotDir}, nil
}
func (s *ChrootService) DeletePreview(ctx context.Context, name string) (map[string]any, error) {
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil || r == nil {
		if e == nil {
			e = fmt.Errorf("unknown chroot: %s", name)
		}
		return nil, e
	}
	rt, _ := s.C.RuntimeFor(name, "")
	root, e := contained(rt.Config.ChrootRoot, r.Path, "registered chroot path")
	if e != nil {
		return nil, e
	}
	return map[string]any{"ok": true, "kind": "delete", "name": name, "path": root, "reclaim_bytes": directorySize(root)}, nil
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
	if archive == "" {
		archive = filepath.Clean("./" + name + ".tar.zst")
	}
	archive, _ = filepath.Abs(archive)
	blocking := []map[string]string{}
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
func (s *ChrootService) packageInventory(ctx context.Context, name string) (map[string]bool, error) {
	r, rt, root, e := s.requireRunnable(ctx, name)
	if e != nil {
		return nil, e
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
