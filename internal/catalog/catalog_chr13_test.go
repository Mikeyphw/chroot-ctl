package catalog

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"chrootctl/internal/config"
)

func TestCHR13CatalogSafetyMetadataAndBlockedSyncUID(t *testing.T) {
	c := Catalog{Kind: "tool", ResourceRoot: "../../resources"}
	entry, err := c.Get("sync-uid")
	if err != nil {
		t.Fatal(err)
	}
	if entry.State != "blocked" || !entry.IsBlocked() || entry.RiskLevel != "blocked" {
		t.Fatalf("sync-uid policy not blocked: %#v", entry)
	}
	if entry.ScriptSHA256 == "" || entry.Source != "builtin" {
		t.Fatalf("missing source/hash metadata: %#v", entry)
	}
}

func TestCHR13PythonManifestRejected(t *testing.T) {
	_, _, err := parseManifest("name: pytool\ndescription: python tool\ndistro: ubuntu\nscript: x.py\n", "x.yaml", "tool", "print('x')")
	if err == nil || !strings.Contains(err.Error(), "invalid script path") {
		t.Fatalf("expected python script rejection, got %v", err)
	}
}

func TestCHR13ExternalParentAndHashValidation(t *testing.T) {
	root := t.TempDir()
	manifestDir := filepath.Join(root, "manifests")
	scriptDir := filepath.Join(root, "scripts")
	if err := os.MkdirAll(manifestDir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(scriptDir, 0o700); err != nil {
		t.Fatal(err)
	}
	script := []byte("#!/bin/sh\necho ok\n")
	sum := sha256.Sum256(script)
	if err := os.WriteFile(filepath.Join(scriptDir, "hello.sh"), script, 0o600); err != nil {
		t.Fatal(err)
	}
	manifest := []byte("name: hello\ndescription: Hello\ndistro: ubuntu\ncategories:\n- system\nscript: hello.sh\nsha256: " + hex.EncodeToString(sum[:]) + "\n")
	if err := os.WriteFile(filepath.Join(manifestDir, "hello.yaml"), manifest, 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := &config.ChrootConfig{ToolManifestDirs: []string{manifestDir}, ToolScriptDirs: []string{scriptDir}}
	entries, err := (Catalog{Kind: "tool", Config: cfg}).LoadAll()
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, entry := range entries {
		if entry.Name == "hello" {
			found = true
			if entry.Source != "external" || entry.ScriptSHA256 != hex.EncodeToString(sum[:]) {
				t.Fatalf("bad external metadata: %#v", entry)
			}
		}
	}
	if !found {
		t.Fatal("external entry not loaded")
	}
}

func TestCHR13EntryMetadataState(t *testing.T) {
	entry := Entry{Kind: "tool", Name: "setup", State: "available", StateReason: "ready"}
	stateful := entry.WithMetadataState(map[string]any{"catalog_state": map[string]any{"tool": map[string]any{"setup": map[string]any{"state": "completed"}}}})
	if !stateful.Installed || stateful.StateReason == "ready" {
		t.Fatalf("metadata state not surfaced: %#v", stateful)
	}
	blocked := Entry{Kind: "tool", Name: "sync-uid", State: "blocked", StateReason: "host-managed"}.WithMetadataState(map[string]any{"catalog_state": map[string]any{"tool": map[string]any{"sync-uid": map[string]any{"state": "completed"}}}})
	if blocked.State != "blocked" || blocked.Installed {
		t.Fatalf("blocked state was overwritten: %#v", blocked)
	}
}

func TestCHR13NoBuiltinArchFullUpgrade(t *testing.T) {
	for _, kind := range []string{"tool", "addon"} {
		entries, err := (Catalog{Kind: kind, ResourceRoot: "../../resources"}).LoadAll()
		if err != nil {
			t.Fatal(err)
		}
		for _, entry := range entries {
			if strings.Contains(entry.ScriptText, "pacman -Syu") || strings.Contains(entry.ScriptText, "pacman -Suy") {
				t.Fatalf("%s %s still performs full system upgrade", kind, entry.Name)
			}
		}
	}
}

func TestCHR13ApplyRejectsBlockedBeforeRunner(t *testing.T) {
	c := Catalog{Kind: "tool", ResourceRoot: "../../resources"}
	_, err := c.Apply(context.Background(), "sync-uid", config.ChrootConfig{DistroName: "missing"}, nil, nil)
	if err == nil || !strings.Contains(err.Error(), "registry is nil") {
		// nil registry remains the first hard contract, keeping this test from depending on root setup.
		t.Fatalf("unexpected error: %v", err)
	}
}
