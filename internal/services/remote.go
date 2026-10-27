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
	provider, _ := rcloneops.SelectedProvider()
	if provider == "" {
		provider = "chrootctl"
	}
	unavailable := "bundled rclone runtime is unavailable"
	probeFailed := "bundled rclone runtime probe failed"
	expected := "/data/adb/modules/chrootctl/runtime/arm64-v8a/rclone"
	remediation := "Rebuild or reinstall the sealed root module with rclone bundled, or explicitly provide a trusted CHROOTCTL_RCLONE_PATH for recovery."
	probeRemediation := "Rebuild the packaged rclone runtime and reinstall the sealed module before retrying remote operations."
	if provider == "skybind" {
		unavailable = "Skybind rclone provider is unavailable"
		probeFailed = "Skybind rclone provider probe failed"
		expected = "/data/adb/modules/skybind/system/bin/skybind-rclone"
		remediation = "Verify Skybind API-01 module provenance and root-private config. No fallback to Chrootctl's rclone is allowed."
		probeRemediation = "Repair Skybind's trusted native rclone installation. Do not change SELinux, copy credentials or fall back implicitly."
	}
	runtime, err := s.C.RcloneRuntime()
	if err != nil {
		return map[string]any{
			"available": false, "configured": false,
			"error":             unavailable,
			"provider":          provider,
			"reason":            "No trusted Android/arm64 rclone executable passed runtime discovery and seal validation.",
			"expected_path":     expected,
			"check":             "Verify the active module runtime inventory, rclone executable ownership/mode, and runtime-manifest seal.",
			"remediation":       remediation,
			"technical_details": err.Error(),
		}, nil
	}
	info, err := runtime.Probe(ctx)
	if err != nil {
		return map[string]any{
			"available": false, "configured": false,
			"error":             probeFailed,
			"provider":          provider,
			"reason":            "A trusted rclone executable was discovered, but its version probe did not complete successfully.",
			"expected_path":     runtime.Executable,
			"check":             "Verify the packaged executable is Android/arm64, executable, and runnable under the root-module environment.",
			"remediation":       probeRemediation,
			"technical_details": err.Error(),
		}, nil
	}
	names := append([]string(nil), info.ConfiguredRemotes...)
	sort.Strings(names)
	return map[string]any{
		"available":     true,
		"provider":      info.Provider,
		"configured":    len(names) > 0,
		"version":       info.Version,
		"remotes":       names,
		"expected_path": info.Executable,
		"check":         "Runtime discovery and version probe passed.",
		"remediation":   "No runtime remediation is required.",
		"checked_at":    time.Now().UTC().Format(time.RFC3339),
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
	_ = path
	return map[string]any{"configured": len(rows) > 0, "remotes": rows, "staged_config_removed": stagedRemoved}, nil
}

func (s *TransferService) RcloneImportConfig(ctx context.Context, sourcePath string) (map[string]any, error) {
	return s.rcloneImportConfig(ctx, sourcePath, false)
}

func (s *TransferService) RcloneImportConfigFromStaging(ctx context.Context, stagedPath string) (map[string]any, error) {
	return s.rcloneImportConfig(ctx, stagedPath, true)
}
