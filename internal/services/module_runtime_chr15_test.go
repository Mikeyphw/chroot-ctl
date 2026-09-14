package services

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCHR15ModuleBuildTargetsRequireResolvedInstalledPath(t *testing.T) {
	ctx := context.Background()
	c := testContainer(t)
	arch := "arm64"
	// Insert a legacy/corrupt registry row directly: normal Registry.Upsert now
	// rejects identity/path basename drift before it can reach module preflight,
	// but module builds must still fail closed if an older database contains it.
	if _, err := c.Registry.DB().ExecContext(ctx, `INSERT INTO chroots (name,distro,path,arch,phase,installed,metadata_json) VALUES (?,?,?,?,?,?,?)`, "work", "ubuntu", filepath.Join(c.BaseConfig.ChrootRoot, "other"), arch, "finalize", 1, "{}"); err != nil {
		t.Fatal(err)
	}
	_, err := c.ModuleBuilder().ResolveStartupTargets(ctx, ModuleBuildRequest{StartupTargets: []string{"work"}})
	if err == nil || !strings.Contains(err.Error(), "failed path validation") {
		t.Fatalf("expected path validation failure, got %v", err)
	}
}

func TestCHR15ModuleBuildPreflightReportsRuntimeAndTargetBlocking(t *testing.T) {
	ctx := context.Background()
	c := testContainer(t)
	preview, err := c.ModuleBuilder().Preflight(ctx, ModuleBuildRequest{StartupTargets: []string{"missing"}})
	if err != nil {
		t.Fatal(err)
	}
	if preview["ok"] == true {
		t.Fatalf("preflight unexpectedly ok: %+v", preview)
	}
	codes := map[string]bool{}
	for _, row := range preview["blocking"].([]map[string]string) {
		codes[row["code"]] = true
	}
	for _, want := range []string{"invalid_startup_targets", "native_runtime_unavailable"} {
		if !codes[want] {
			t.Fatalf("missing preflight code %s in %+v", want, preview["blocking"])
		}
	}
}

func TestCHR15ModuleRuntimeCandidateRequiresPackageSeal(t *testing.T) {
	root := t.TempDir()
	for _, rel := range []string{"system/bin/chrootctl", "bin/chrootctl-magisk-helper", "config/chrootctl/compatibility-manifest.json", "runtime/arm64-v8a/runtime-manifest.json", "runtime/arm64-v8a/chrootctl"} {
		path := filepath.Join(root, rel)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("x"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(root, "module.prop"), []byte("id=chrootctl-magisk\nversionCode=15\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	c := testContainer(t)
	status := c.ModuleRuntime().candidate(root, false)
	if status["packageSealReady"] == true || status["layoutReady"] == true {
		t.Fatalf("candidate without package manifest should not be ready: %+v", status)
	}
}
