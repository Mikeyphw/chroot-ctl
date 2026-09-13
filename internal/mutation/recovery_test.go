package mutation

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"chrootctl/internal/config"
	"chrootctl/internal/registry"
)

func testRegistry(t *testing.T) *registry.Registry {
	t.Helper()
	r, err := registry.Open(filepath.Join(t.TempDir(), "registry.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = r.Close() })
	return r
}
func putChroot(t *testing.T, r *registry.Registry, name, path string, meta map[string]any) {
	t.Helper()
	if err := r.Upsert(context.Background(), registry.ChrootInput{Name: name, Distro: "ubuntu", Path: path, Phase: "finalize", Installed: true, Metadata: meta}); err != nil {
		t.Fatal(err)
	}
}

func TestRecoveryRollsBackInterruptedRemove(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	src := filepath.Join(root, "alpha")
	tomb := filepath.Join(root, ".alpha.remove")
	if err := os.MkdirAll(src, 0755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "alpha", src, nil)
	id, err := r.BeginFSMutation(ctx, "chroot-remove", "alpha", src, tomb, map[string]any{"tombstone": tomb})
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(src, tomb); err != nil {
		t.Fatal(err)
	}
	if err = r.UpdateFSMutation(ctx, id, registry.FSMutationPromoting, map[string]any{"tombstone": tomb}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	report, err := e.RecoverLocked(ctx, "alpha")
	if err != nil {
		t.Fatal(err)
	}
	if len(report.Recovered) != 1 || !exists(src) || exists(tomb) {
		t.Fatalf("report=%+v src=%v tomb=%v", report, exists(src), exists(tomb))
	}
}

func TestRecoveryRollsBackInterruptedRename(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	src := filepath.Join(root, "alpha")
	dst := filepath.Join(root, "beta")
	if err := os.MkdirAll(src, 0755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "alpha", src, nil)
	id, err := r.BeginFSMutation(ctx, "chroot-rename", "alpha", src, dst, map[string]any{"new_name": "beta"})
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(src, dst); err != nil {
		t.Fatal(err)
	}
	if err = r.UpdateFSMutation(ctx, id, registry.FSMutationPromoting, map[string]any{"new_name": "beta"}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, "alpha"); err != nil {
		t.Fatal(err)
	}
	if !exists(src) || exists(dst) {
		t.Fatalf("rename recovery did not restore source")
	}
}

func TestRecoveryConsumesCommittedInstallCleanupDebt(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	target := filepath.Join(root, "alpha")
	backup := filepath.Join(root, ".alpha.old")
	stage := filepath.Join(root, ".stage")
	if err := os.MkdirAll(target, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(backup, 0755); err != nil {
		t.Fatal(err)
	}
	id, err := r.BeginFSMutation(ctx, "install.extract", "alpha", stage, target, map[string]any{"stage": stage, "backup": backup, "had_existing": true})
	if err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "alpha", target, map[string]any{"_chrootctl_install_mutation_id": id})
	if err = r.UpdateFSMutation(ctx, id, registry.FSMutationCleanupDebt, map[string]any{"backup": backup}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, "alpha"); err != nil {
		t.Fatal(err)
	}
	if exists(backup) {
		t.Fatal("cleanup debt backup remains")
	}
	rows, err := r.PendingFSMutations(ctx, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 0 {
		t.Fatalf("pending=%+v", rows)
	}
}

func TestRecoveryFailsClosedForUnknownMutationKind(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	_, err := r.BeginFSMutation(ctx, "unknown.kind", "alpha", "/a", "/b", nil)
	if err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	_, err = e.RecoverLocked(ctx, "alpha")
	var required RecoveryRequiredError
	if !errors.As(err, &required) {
		t.Fatalf("err=%v", err)
	}
}

func TestRecoveryRollsBackInterruptedImportAfterBackupRename(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	target := filepath.Join(root, "alpha")
	backup := filepath.Join(root, ".alpha.backup")
	stage := filepath.Join(root, ".alpha.stage")
	if err := os.MkdirAll(backup, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(backup, "old"), []byte("old"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(stage, 0755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "alpha", target, nil)
	id, err := r.BeginFSMutation(ctx, "chroot.import", "alpha", "/archive.tar.zst", target, map[string]any{"stage": stage, "backup": backup, "had_existing": true})
	if err != nil {
		t.Fatal(err)
	}
	if err = r.UpdateFSMutation(ctx, id, registry.FSMutationPromoting, map[string]any{"stage": stage, "backup": backup, "had_existing": true}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, "alpha"); err != nil {
		t.Fatal(err)
	}
	if !exists(target) || exists(backup) || exists(stage) {
		t.Fatalf("rollback result target=%v backup=%v stage=%v", exists(target), exists(backup), exists(stage))
	}
	if _, err := os.Stat(filepath.Join(target, "old")); err != nil {
		t.Fatalf("old target content was not restored: %v", err)
	}
}

func TestRecoveryFinishesCommittedImportCleanupDebt(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	target := filepath.Join(root, "alpha")
	backup := filepath.Join(root, ".alpha.backup")
	if err := os.MkdirAll(target, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(backup, 0755); err != nil {
		t.Fatal(err)
	}
	id, err := r.BeginFSMutation(ctx, "chroot.import", "alpha", "/archive.tar.zst", target, map[string]any{"backup": backup, "had_existing": true})
	if err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "alpha", target, map[string]any{"_chrootctl_mutation_id": id})
	if err = r.UpdateFSMutation(ctx, id, registry.FSMutationCommitted, map[string]any{"backup": backup, "had_existing": true}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, "alpha"); err != nil {
		t.Fatal(err)
	}
	if exists(backup) {
		t.Fatal("committed import backup was not cleaned")
	}
	rows, err := r.PendingFSMutations(ctx, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 0 {
		t.Fatalf("pending rows after committed recovery: %+v", rows)
	}
}

func TestRecoveryFailsClosedWhenExpectedBackupIsMissing(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	target := filepath.Join(root, "alpha")
	stage := filepath.Join(root, ".alpha.stage")
	backup := filepath.Join(root, ".alpha.missing")
	if err := os.MkdirAll(stage, 0755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "alpha", target, nil)
	id, err := r.BeginFSMutation(ctx, "chroot.import", "alpha", "/archive.tar.zst", target, map[string]any{"stage": stage, "backup": backup, "had_existing": true})
	if err != nil {
		t.Fatal(err)
	}
	if err = r.UpdateFSMutation(ctx, id, registry.FSMutationPromoting, map[string]any{"stage": stage, "backup": backup, "had_existing": true}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	_, err = e.RecoverLocked(ctx, "alpha")
	var required RecoveryRequiredError
	if !errors.As(err, &required) {
		t.Fatalf("expected repair-required error, got %v", err)
	}
	rows, qerr := r.PendingFSMutations(ctx, 0)
	if qerr != nil {
		t.Fatal(qerr)
	}
	if len(rows) != 1 || rows[0].State != registry.FSMutationRepairRequired {
		t.Fatalf("missing durable repair-required state: %+v", rows)
	}
}

func TestRecoveryRecognizesCommittedSnapshotCreate(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	chrootPath := filepath.Join(root, "alpha")
	snapshotPath := filepath.Join(root, "snapshots", "snap1")
	stage := filepath.Join(root, "snapshots", ".partial-snap1")
	if err := os.MkdirAll(chrootPath, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(snapshotPath, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(stage, 0755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "alpha", chrootPath, nil)
	id, err := r.BeginFSMutation(ctx, "snapshot.create", "alpha", chrootPath, snapshotPath, map[string]any{"snapshot": "snap1", "stage": stage})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = r.AddSnapshot(ctx, registry.SnapshotInput{Name: "snap1", ChrootName: "alpha", Path: snapshotPath, Kind: "copy", Metadata: map[string]any{"_chrootctl_mutation_id": id}}); err != nil {
		t.Fatal(err)
	}
	if err = r.UpdateFSMutation(ctx, id, registry.FSMutationPromoting, map[string]any{"snapshot": "snap1", "stage": stage}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, "alpha"); err != nil {
		t.Fatal(err)
	}
	if exists(stage) {
		t.Fatal("snapshot recovery left stale stage")
	}
	rows, err := r.PendingFSMutations(ctx, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 0 {
		t.Fatalf("snapshot mutation still pending: %+v", rows)
	}
}

func TestCHR07RecoveryCompletesCommittedRenameNamespaceAndOverride(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	src := filepath.Join(root, "old")
	dst := filepath.Join(root, "new")
	if err := os.MkdirAll(dst, 0o755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "old", src, nil)
	oldMove := filepath.Join(root, "state", "old-demo.state")
	newMove := filepath.Join(root, "state", "new-demo.state")
	if err := os.MkdirAll(filepath.Dir(oldMove), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(oldMove, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfgPath := filepath.Join(root, "config.json")
	if err := os.WriteFile(cfgPath, []byte(`{"chroot_overrides":{"old":{"locale":"pt_BR.UTF-8"}}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	id, err := r.BeginFSMutation(ctx, "chroot-rename", "old", src, dst, map[string]any{"new_name": "new", "namespace_moves": []map[string]any{{"from": oldMove, "to": newMove}}, "config_override": true, "config_path": cfgPath})
	if err != nil {
		t.Fatal(err)
	}
	if err := r.Rename(ctx, "old", "new", &dst); err != nil {
		t.Fatal(err)
	}
	if err := r.UpdateFSMutation(ctx, id, registry.FSMutationCommitted, map[string]any{"new_name": "new", "namespace_moves": []map[string]any{{"from": oldMove, "to": newMove}}, "config_override": true, "config_path": cfgPath}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, "new"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(newMove); err != nil {
		t.Fatalf("namespace move not completed: %v", err)
	}
	cfg, err := config.LoadReadOnly(cfgPath, config.WithRuntime(config.RuntimeContext{Home: root}))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := cfg.ChrootOverrides["new"]; !ok {
		t.Fatal("override not recovered")
	}
	if _, ok := cfg.ChrootOverrides["old"]; ok {
		t.Fatal("old override remains")
	}
}

func TestCHR07RecoveryRollsBackRenameNamespaceBeforeRegistryCommit(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	src := filepath.Join(root, "old")
	dst := filepath.Join(root, "new")
	if err := os.MkdirAll(dst, 0o755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "old", src, nil)
	oldMove := filepath.Join(root, "state", "old-demo.state")
	newMove := filepath.Join(root, "state", "new-demo.state")
	if err := os.MkdirAll(filepath.Dir(newMove), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(newMove, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfgPath := filepath.Join(root, "config.json")
	if err := os.WriteFile(cfgPath, []byte(`{"chroot_overrides":{"new":{"locale":"pt_BR.UTF-8"}}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	id, err := r.BeginFSMutation(ctx, "chroot-rename", "old", src, dst, map[string]any{"new_name": "new", "namespace_moves": []map[string]any{{"from": oldMove, "to": newMove}}, "config_override": true, "config_path": cfgPath})
	if err != nil {
		t.Fatal(err)
	}
	if err := r.UpdateFSMutation(ctx, id, registry.FSMutationPromoting, map[string]any{"new_name": "new", "namespace_moves": []map[string]any{{"from": oldMove, "to": newMove}}, "config_override": true, "config_path": cfgPath}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, "old"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(src); err != nil {
		t.Fatalf("root not rolled back: %v", err)
	}
	if _, err := os.Stat(oldMove); err != nil {
		t.Fatalf("namespace not rolled back: %v", err)
	}
	cfg, err := config.LoadReadOnly(cfgPath, config.WithRuntime(config.RuntimeContext{Home: root}))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := cfg.ChrootOverrides["old"]; !ok {
		t.Fatal("config override was not rolled back to old identity")
	}
	if _, ok := cfg.ChrootOverrides["new"]; ok {
		t.Fatal("new config override remains after rollback")
	}
}

func TestCHR07RecoveryFinishesCommittedRemoveNamespaceAndOverride(t *testing.T) {
	ctx := context.Background()
	r := testRegistry(t)
	root := t.TempDir()
	src := filepath.Join(root, "old")
	tomb := filepath.Join(root, ".old.remove")
	if err := os.MkdirAll(tomb, 0o755); err != nil {
		t.Fatal(err)
	}
	putChroot(t, r, "old", src, nil)
	staged := filepath.Join(root, "old-demo.state.chrootctl-remove-x")
	if err := os.WriteFile(staged, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfgPath := filepath.Join(root, "config.json")
	if err := os.WriteFile(cfgPath, []byte(`{"chroot_overrides":{"old":{"locale":"pt_BR.UTF-8"}}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	id, err := r.BeginFSMutation(ctx, "chroot-remove", "old", src, tomb, map[string]any{"namespace_moves": []map[string]any{{"from": filepath.Join(root, "old-demo.state"), "to": staged}}, "config_override": true, "config_path": cfgPath})
	if err != nil {
		t.Fatal(err)
	}
	if err := r.Delete(ctx, "old"); err != nil {
		t.Fatal(err)
	}
	if err := r.UpdateFSMutation(ctx, id, registry.FSMutationCommitted, map[string]any{"namespace_moves": []map[string]any{{"from": filepath.Join(root, "old-demo.state"), "to": staged}}, "config_override": true, "config_path": cfgPath}); err != nil {
		t.Fatal(err)
	}
	e := New(r, filepath.Join(root, "ops"), false)
	if _, err = e.RecoverLocked(ctx, ""); err != nil {
		t.Fatal(err)
	}
	if exists(tomb) || exists(staged) {
		t.Fatal("committed remove cleanup debt remains")
	}
	cfg, err := config.LoadReadOnly(cfgPath, config.WithRuntime(config.RuntimeContext{Home: root}))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := cfg.ChrootOverrides["old"]; ok {
		t.Fatal("removed override remains")
	}
}
