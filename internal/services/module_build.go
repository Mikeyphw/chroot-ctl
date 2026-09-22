package services

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	chmodule "chrootctl/internal/module"
	"chrootctl/internal/validation"
)

type ModuleBuildService struct{ C *Container }

type ModuleBuildRequest struct {
	Archive        string
	StartupTargets []string
	AllInstalled   bool
}

func (s *ModuleBuildService) runtimeDir() (string, error) {
	if status := s.C.ModuleRuntime().Status(); status["active"] != nil {
		if active, ok := status["active"].(map[string]any); ok {
			if root := strings.TrimSpace(fmt.Sprint(active["path"])); root != "" {
				candidate := filepath.Join(root, "runtime", chmodule.RuntimeABI)
				if err := chmodule.ValidateRuntime(candidate); err == nil {
					return candidate, nil
				}
			}
		}
	}
	// When launched through system/bin/chrootctl the shell launcher execs the
	// bundled runtime ELF, so os.Executable normally points at the sealed runtime.
	exe, err := os.Executable()
	if err == nil {
		candidate := filepath.Dir(exe)
		if err := chmodule.ValidateRuntime(candidate); err == nil {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("no sealed Go-native Android runtime is available for module packaging")
}

func (s *ModuleBuildService) ResolveStartupTargets(ctx context.Context, req ModuleBuildRequest) ([]string, error) {
	return s.targets(ctx, req)
}

func (s *ModuleBuildService) Preflight(ctx context.Context, req ModuleBuildRequest) (map[string]any, error) {
	archive := strings.TrimSpace(req.Archive)
	if archive == "" {
		archive = ManagedArchive("chrootctl", "zip")
	}
	blocking := []map[string]string{}
	warn := func(code, msg string) { blocking = append(blocking, map[string]string{"code": code, "message": msg}) }
	managedRoot, err := EnsureManagedTransferRoot()
	if err != nil {
		warn("managed_root_unavailable", err.Error())
	} else if abs, err := filepath.Abs(archive); err != nil {
		warn("invalid_archive_path", err.Error())
	} else if managed, err := contained(managedRoot, abs, "module artifact"); err != nil {
		warn("archive_outside_managed_root", err.Error())
	} else {
		archive = managed
	}
	targets := []string{}
	if t, err := s.targets(ctx, req); err != nil {
		warn("invalid_startup_targets", err.Error())
	} else {
		targets = t
	}
	runtimeDir := ""
	if r, err := s.runtimeDir(); err != nil {
		warn("native_runtime_unavailable", err.Error())
	} else {
		runtimeDir = r
	}
	return map[string]any{"ok": len(blocking) == 0, "kind": "system.module_build", "archive": archive, "startupTargets": targets, "allInstalled": req.AllInstalled, "runtimeDir": runtimeDir, "blocking": blocking, "warnings": []string{"Module artifacts are published under the managed transfer root.", "Startup targets are resolved through the same installed-target gate used by module builds."}, "confirm": false}, nil
}

func (s *ModuleBuildService) targets(ctx context.Context, req ModuleBuildRequest) ([]string, error) {
	rows, err := s.C.Registry.List(ctx)
	if err != nil {
		return nil, err
	}
	installed := map[string]bool{}
	all := []string{}
	for _, row := range rows {
		if row.Installed {
			installed[row.Name] = true
			all = append(all, row.Name)
		}
	}
	requested := append([]string(nil), req.StartupTargets...)
	if req.AllInstalled {
		requested = append(requested, all...)
	}
	seen := map[string]bool{}
	out := []string{}
	for _, raw := range requested {
		name, err := validation.ChrootName(strings.TrimSpace(raw))
		if err != nil {
			return nil, err
		}
		if !installed[name] {
			return nil, fmt.Errorf("module startup target is not an installed chroot: %s", name)
		}
		resolved, err := s.C.ResolveTarget(ctx, name, true)
		if err != nil {
			return nil, fmt.Errorf("module startup target %s failed path validation: %w", name, err)
		}
		if resolved == nil || !resolved.Record.Installed {
			return nil, fmt.Errorf("module startup target is not an installed chroot: %s", name)
		}
		if !seen[name] {
			seen[name] = true
			out = append(out, name)
		}
	}
	sort.Strings(out)
	return out, nil
}

func (s *ModuleBuildService) Build(ctx context.Context, req ModuleBuildRequest) (map[string]any, error) {
	archive := strings.TrimSpace(req.Archive)
	if archive == "" {
		archive = ManagedArchive("chrootctl", "zip")
	}
	managedRoot, err := EnsureManagedTransferRoot()
	if err != nil {
		return nil, err
	}
	abs, err := filepath.Abs(archive)
	if err != nil {
		return nil, err
	}
	abs, err = contained(managedRoot, abs, "module artifact")
	if err != nil {
		return nil, err
	}
	if err = os.MkdirAll(filepath.Dir(abs), 0o700); err != nil {
		return nil, err
	}
	targets, err := s.targets(ctx, req)
	if err != nil {
		return nil, err
	}
	runtimeDir, err := s.runtimeDir()
	if err != nil {
		return nil, err
	}
	out, err := os.MkdirTemp(filepath.Dir(abs), ".chrootctl-module-tree-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(out)
	if err = chmodule.Render(chmodule.Options{OutputDir: out, ZipPath: abs, NativeRuntimeDir: runtimeDir, StartupTargets: targets}); err != nil {
		return nil, err
	}
	if err = chmodule.ValidateRendered(out); err != nil {
		return nil, err
	}
	if err = chmodule.ValidateZipArchive(abs); err != nil {
		return nil, err
	}
	data, err := os.ReadFile(abs)
	if err != nil {
		return nil, err
	}
	h := sha256.Sum256(data)
	sha := hex.EncodeToString(h[:])
	metadata := map[string]any{"sha256": sha, "startup_targets": targets, "runtime_dir": runtimeDir, "module_id": chmodule.ModuleID, "module_version": chmodule.ModuleVersion, "module_version_code": chmodule.ModuleVersionCode, "package_manifest": chmodule.ModulePackageManifestPath}
	artifact, err := s.C.Transfer().RegisterArtifact(ctx, abs, "module-archive", "", nil, metadata)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"built":                 true,
		"archive":               abs,
		"sizeBytes":             len(data),
		"sha256":                sha,
		"startupTargets":        targets,
		"runtimeDir":            runtimeDir,
		"moduleId":              chmodule.ModuleID,
		"moduleVersion":         chmodule.ModuleVersion,
		"moduleVersionCode":     chmodule.ModuleVersionCode,
		"packageManifest":       chmodule.ModulePackageManifestPath,
		"bridgeProtocolVersion": chmodule.BridgeProtocolVersion,
		"artifact":              artifact,
	}, nil
}
