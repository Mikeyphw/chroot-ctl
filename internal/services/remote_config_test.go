package services

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestManagedRcloneConfigImportRemovesStagedCredentialCopy(t *testing.T) {
	root := t.TempDir()
	transferRoot := filepath.Join(root, "transfer")
	configPath := filepath.Join(root, "private", "rclone.conf")
	rclonePath := filepath.Join(root, "rclone")
	if err := os.WriteFile(rclonePath, []byte("#!/bin/sh\nexit 0\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CHROOTCTL_TRANSFER_DIR", transferRoot)
	t.Setenv("CHROOTCTL_RCLONE_PATH", rclonePath)
	t.Setenv("CHROOTCTL_RCLONE_CONFIG", configPath)

	c := testContainer(t)
	if err := os.MkdirAll(transferRoot, 0o700); err != nil {
		t.Fatal(err)
	}
	staged := filepath.Join(transferRoot, "rclone.conf")
	body := []byte("[drive]\ntype = local\n")
	if err := os.WriteFile(staged, body, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Transfer().RegisterArtifact(context.Background(), staged, "staged-import", "", nil, map[string]any{"contains_credentials": true}); err != nil {
		t.Fatal(err)
	}

	result, err := c.Transfer().RcloneImportConfigFromStaging(context.Background(), staged)
	if err != nil {
		t.Fatal(err)
	}
	if removed, _ := result["staged_config_removed"].(bool); !removed {
		t.Fatalf("staged cleanup result = %#v", result)
	}
	if _, err := os.Stat(staged); !os.IsNotExist(err) {
		t.Fatalf("staged credential copy still exists: %v", err)
	}
	if artifact, err := c.Registry.ArtifactByPath(context.Background(), staged); err != nil || artifact != nil {
		t.Fatalf("staged artifact row=%#v err=%v", artifact, err)
	}
	got, err := os.ReadFile(configPath)
	if err != nil || string(got) != string(body) {
		t.Fatalf("private config=%q err=%v", got, err)
	}
	st, err := os.Stat(configPath)
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode().Perm() != 0o600 {
		t.Fatalf("private config mode=%v", st.Mode().Perm())
	}
}
