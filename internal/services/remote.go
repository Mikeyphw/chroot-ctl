package services

import (
	"context"
	"fmt"
	"os"
	"sort"
	"time"

	"chrootctl/internal/rcloneops"
)

func (s *Container) RcloneRuntime() (rcloneops.Runtime, error) {
	return rcloneops.RuntimeFromEnvironment()
}

func (s *TransferService) RcloneStatus(ctx context.Context) (map[string]any, error) {
	runtime, err := s.C.RcloneRuntime()
	if err != nil {
		return map[string]any{"available": false, "configured": false, "error": err.Error()}, nil
	}
	info, err := runtime.Probe(ctx)
	if err != nil {
		return nil, err
	}
	names := append([]string(nil), info.ConfiguredRemotes...)
	sort.Strings(names)
	return map[string]any{
		"available":  true,
		"configured": len(names) > 0,
		"version":    info.Version,
		"executable": info.Executable,
		"config":     info.Config,
		"remotes":    names,
		"checked_at": time.Now().UTC().Format(time.RFC3339),
	}, nil
}

func (s *TransferService) RcloneList(ctx context.Context, location string) (map[string]any, error) {
	runtime, err := s.C.RcloneRuntime()
	if err != nil {
		return nil, err
	}
	entries, err := runtime.List(ctx, location)
	if err != nil {
		return nil, err
	}
	items := make([]map[string]any, 0, len(entries))
	for _, entry := range entries {
		child, joinErr := rcloneops.JoinURI(location, entry.Name)
		if joinErr != nil {
			return nil, joinErr
		}
		items = append(items, map[string]any{"name": entry.Name, "path": child, "size_bytes": entry.Size, "is_dir": entry.IsDir, "modified_at": entry.ModTime.UTC().Format(time.RFC3339)})
	}
	return map[string]any{"location": location, "items": items, "count": len(items)}, nil
}

func (s *TransferService) rcloneImportConfig(ctx context.Context, sourcePath string, requireManaged bool) (map[string]any, error) {
	if sourcePath == "" {
		return nil, fmt.Errorf("rclone config source path is required")
	}
	managedSource := ""
	if requireManaged {
		resolved, err := s.managed(sourcePath)
		if err != nil {
			return nil, fmt.Errorf("rclone config must be imported from managed staging: %w", err)
		}
		managedSource = resolved
		sourcePath = resolved
	}
	path, err := rcloneops.ImportConfig(sourcePath)
	if err != nil {
		return nil, err
	}
	runtime, err := rcloneops.RuntimeFromEnvironment()
	if err != nil {
		return nil, err
	}
	names, err := runtime.ConfiguredRemoteNames()
	if err != nil {
		return nil, err
	}
	rows := make([]string, 0, len(names))
	for name := range names {
		rows = append(rows, name)
	}
	sort.Strings(rows)
	stagedRemoved := false
	if managedSource != "" {
		// The staged SAF copy contains provider credentials. Once the private
		// root-owned config has been published, remove the staging copy rather
		// than leaving a second credential file in the transfer artifact plane.
		if removeErr := os.Remove(managedSource); removeErr != nil && !os.IsNotExist(removeErr) {
			return nil, fmt.Errorf("rclone config imported but staged credential cleanup failed: %w", removeErr)
		}
		_ = os.Remove(managedSource + ".sha256")
		if artifact, lookupErr := s.C.Registry.ArtifactByPath(ctx, managedSource); lookupErr != nil {
			return nil, fmt.Errorf("rclone config imported but staged artifact lookup failed: %w", lookupErr)
		} else if artifact != nil {
			if deleteErr := s.C.Registry.DeleteArtifact(ctx, artifact.ArtifactID); deleteErr != nil {
				return nil, fmt.Errorf("rclone config imported but staged artifact cleanup failed: %w", deleteErr)
			}
		}
		stagedRemoved = true
	}
	return map[string]any{"configured": len(rows) > 0, "config": path, "remotes": rows, "staged_config_removed": stagedRemoved}, nil
}

func (s *TransferService) RcloneImportConfig(ctx context.Context, sourcePath string) (map[string]any, error) {
	return s.rcloneImportConfig(ctx, sourcePath, false)
}

func (s *TransferService) RcloneImportConfigFromStaging(ctx context.Context, stagedPath string) (map[string]any, error) {
	return s.rcloneImportConfig(ctx, stagedPath, true)
}
