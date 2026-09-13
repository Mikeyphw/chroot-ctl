package services

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"chrootctl/internal/config"
	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
)

func prepareCRUDTarget(t *testing.T, name string) *Container {
	t.Helper()
	c := testContainer(t)
	root := filepath.Join(c.BaseConfig.ChrootRoot, name)
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "marker"), []byte(name), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := c.Registry.Upsert(context.Background(), registry.ChrootInput{Name: name, Distro: "ubuntu", Path: root, Phase: "finalize", Installed: true}); err != nil {
		t.Fatal(err)
	}
	return c
}

func withNoopUnmount(t *testing.T) {
	t.Helper()
	old := crudUnmountTarget
	crudUnmountTarget = func(context.Context, Runtime) model.OperationResult { return model.OperationResult{} }
	t.Cleanup(func() { crudUnmountTarget = old })
}

func TestCHR07RenameMigratesIdentityNamespaceAtomically(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	cfgPath := filepath.Join(filepath.Dir(c.BaseConfig.DatabasePath), "config.json")
	if err := os.WriteFile(cfgPath, []byte(`{"chroot_overrides":{"old":{"locale":"pt_BR.UTF-8","extra_packages":["git"]}}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	c.ConfigPath = cfgPath
	c.BaseConfig.ChrootOverrides["old"] = map[string]any{"locale": "pt_BR.UTF-8", "extra_packages": []any{"git"}}

	snapDir := filepath.Join(c.Snapshots().Root(), "old", "before")
	if err := os.MkdirAll(snapDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(snapDir, "snapshot-marker"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Registry.AddSnapshot(ctx, registry.SnapshotInput{Name: "before", ChrootName: "old", Path: snapDir, Kind: "copy", SizeBytes: 1}); err != nil {
		t.Fatal(err)
	}

	identity := filepath.Join(c.BaseConfig.ServiceStateDir, "old-demo.service.identity.json")
	if err := writeIdentity(identity, &sys.ProcessIdentity{PID: 99999999}); err != nil {
		t.Fatal(err)
	}
	pid := filepath.Join(c.BaseConfig.ServiceStateDir, "old-demo.service.pid")
	if err := os.WriteFile(pid, []byte("99999999\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	log := filepath.Join(c.BaseConfig.ServiceLogDir, "old-demo.service.log")
	if err := os.WriteFile(log, []byte("log"), 0o600); err != nil {
		t.Fatal(err)
	}
	enabled := filepath.Join(c.BaseConfig.ServiceStateDir, "targets", "boot.target.wants", "old-demo.service.enabled")
	if err := os.MkdirAll(filepath.Dir(enabled), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(enabled, []byte("enabled"), 0o600); err != nil {
		t.Fatal(err)
	}

	res, err := c.Chroots().Rename(ctx, "old", "new")
	if err != nil || !res.Renamed {
		t.Fatalf("res=%+v err=%v", res, err)
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "new", "marker")); err != nil {
		t.Fatalf("new root: %v", err)
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("old root still exists: %v", err)
	}
	if row, err := c.Registry.Get(ctx, "new"); err != nil || row == nil || row.Path != filepath.Join(c.BaseConfig.ChrootRoot, "new") {
		t.Fatalf("new row=%+v err=%v", row, err)
	}
	if row, err := c.Registry.Get(ctx, "old"); err != nil || row != nil {
		t.Fatalf("old row=%+v err=%v", row, err)
	}
	newSnap, err := c.Registry.GetSnapshotByName(ctx, "new", "before")
	if err != nil {
		t.Fatal(err)
	}
	wantSnap := filepath.Join(c.Snapshots().Root(), "new", "before")
	if newSnap.Path != wantSnap {
		t.Fatalf("snapshot path=%q want=%q", newSnap.Path, wantSnap)
	}
	if _, err := os.Stat(filepath.Join(wantSnap, "snapshot-marker")); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{
		filepath.Join(c.BaseConfig.ServiceStateDir, "new-demo.service.identity.json"),
		filepath.Join(c.BaseConfig.ServiceStateDir, "new-demo.service.pid"),
		filepath.Join(c.BaseConfig.ServiceLogDir, "new-demo.service.log"),
		filepath.Join(c.BaseConfig.ServiceStateDir, "targets", "boot.target.wants", "new-demo.service.enabled"),
	} {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("migrated namespace missing %s: %v", path, err)
		}
	}
	cfg, err := config.LoadReadOnly(cfgPath, config.WithRuntime(config.RuntimeContext{Home: t.TempDir()}))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := cfg.ChrootOverrides["old"]; ok {
		t.Fatal("old persisted override remains")
	}
	if _, ok := cfg.ChrootOverrides["new"]; !ok {
		t.Fatal("new persisted override missing")
	}
	if _, ok := c.BaseConfig.ChrootOverrides["old"]; ok {
		t.Fatal("old in-memory override remains")
	}
	if _, ok := c.BaseConfig.ChrootOverrides["new"]; !ok {
		t.Fatal("new in-memory override missing")
	}
}

func TestCHR07RenameRegistryFailureRollsBackFilesystemAndNamespace(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	state := filepath.Join(c.BaseConfig.ServiceStateDir, "old-demo.state")
	if err := os.WriteFile(state, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	oldFn := crudRegistryRenameIdentity
	sentinel := errors.New("injected registry failure")
	crudRegistryRenameIdentity = func(*registry.Registry, context.Context, string, string, *string, string, string) error {
		return sentinel
	}
	t.Cleanup(func() { crudRegistryRenameIdentity = oldFn })
	if _, err := c.Chroots().Rename(ctx, "old", "new"); !errors.Is(err, sentinel) {
		t.Fatalf("err=%v", err)
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old", "marker")); err != nil {
		t.Fatal("old root not restored")
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "new")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("new root remains: %v", err)
	}
	if _, err := os.Stat(state); err != nil {
		t.Fatalf("state not rolled back: %v", err)
	}
	if row, _ := c.Registry.Get(ctx, "old"); row == nil {
		t.Fatal("old registry row lost")
	}
	if row, _ := c.Registry.Get(ctx, "new"); row != nil {
		t.Fatal("new registry row unexpectedly exists")
	}
	pending, err := c.Registry.PendingFSMutations(ctx, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 0 {
		t.Fatalf("pending=%+v", pending)
	}
}

func TestCHR07RemoveRegistryFailureRestoresRootAndNamespace(t *testing.T) {
	withNoopUnmount(t)
	ctx := context.Background()
	c := prepareCRUDTarget(t, "gone")
	snap := filepath.Join(c.Snapshots().Root(), "gone", "s1")
	if err := os.MkdirAll(snap, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Registry.AddSnapshot(ctx, registry.SnapshotInput{Name: "s1", ChrootName: "gone", Path: snap}); err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(c.BaseConfig.ServiceStateDir, "gone-demo.state")
	if err := os.WriteFile(state, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	oldFn := crudRegistryDelete
	sentinel := errors.New("injected delete failure")
	crudRegistryDelete = func(*registry.Registry, context.Context, string) error { return sentinel }
	t.Cleanup(func() { crudRegistryDelete = oldFn })
	if _, err := c.Chroots().Remove(ctx, "gone"); !errors.Is(err, sentinel) {
		t.Fatalf("err=%v", err)
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "gone", "marker")); err != nil {
		t.Fatalf("root not restored: %v", err)
	}
	if _, err := os.Stat(snap); err != nil {
		t.Fatalf("snapshot namespace not restored: %v", err)
	}
	if _, err := os.Stat(state); err != nil {
		t.Fatalf("service state not restored: %v", err)
	}
	if row, _ := c.Registry.Get(ctx, "gone"); row == nil {
		t.Fatal("registry row lost")
	}
}

func TestCHR07ActiveManagedServiceBlocksRename(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	id := sys.CaptureProcessIdentity(os.Getpid())
	if id == nil {
		t.Skip("process identity unavailable")
	}
	if err := writeIdentity(filepath.Join(c.BaseConfig.ServiceStateDir, "old-live.service.identity.json"), id); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Chroots().Rename(ctx, "old", "new"); err == nil {
		t.Fatal("active service did not block rename")
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old")); err != nil {
		t.Fatal("blocked rename changed root")
	}
}

func TestCHR07DestinationOverrideCollisionBlocksBeforeMutation(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	c.BaseConfig.ChrootOverrides["new"] = map[string]any{"locale": "pt_BR.UTF-8"}
	if _, err := c.Chroots().Rename(ctx, "old", "new"); err == nil {
		t.Fatal("destination override collision accepted")
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old")); err != nil {
		t.Fatal("rejected rename changed root")
	}
}

func TestCHR07RenameRejectsMountedTargetBeforeMutation(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	oldStatus := crudMountStatus
	crudMountStatus = func(Runtime) []map[string]string { return []map[string]string{{"target": "proc", "mounted": "yes"}} }
	t.Cleanup(func() { crudMountStatus = oldStatus })
	if _, err := c.Chroots().Rename(ctx, "old", "new"); err == nil {
		t.Fatal("mounted target did not block rename")
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old", "marker")); err != nil {
		t.Fatalf("blocked rename changed root: %v", err)
	}
}

func TestCHR07DestructiveTargetRejectsConfiguredManagementRoot(t *testing.T) {
	ctx := context.Background()
	c := testContainer(t)
	name := filepath.Base(c.BaseConfig.ChrootRoot)
	if err := c.Registry.Upsert(ctx, registry.ChrootInput{Name: name, Distro: "ubuntu", Path: c.BaseConfig.ChrootRoot, Phase: "finalize", Installed: true}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Chroots().Rename(ctx, name, "safe"); err == nil {
		t.Fatal("configured management root was accepted as destructive target")
	}
	if _, err := os.Stat(c.BaseConfig.ChrootRoot); err != nil {
		t.Fatalf("management root changed: %v", err)
	}
}

func TestCHR07RenamePropagatesOverrideValidationFailure(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	c.BaseConfig.ChrootOverrides["old"] = map[string]any{"definitely_unknown_key": true}
	if _, err := c.Chroots().Rename(ctx, "old", "new"); err == nil {
		t.Fatal("malformed override was silently ignored")
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old", "marker")); err != nil {
		t.Fatalf("rejected rename changed root: %v", err)
	}
}

func TestCHR07RootRenameFsyncFailureRollsBack(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	oldSync := crudSyncDir
	calls := 0
	sentinel := errors.New("injected root parent fsync failure")
	crudSyncDir = func(path string) error {
		calls++
		if calls == 1 {
			return sentinel
		}
		return oldSync(path)
	}
	t.Cleanup(func() { crudSyncDir = oldSync })
	if _, err := c.Chroots().Rename(ctx, "old", "new"); !errors.Is(err, sentinel) {
		t.Fatalf("err=%v", err)
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old", "marker")); err != nil {
		t.Fatalf("old root not restored: %v", err)
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "new")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("new root remains: %v", err)
	}
}

func TestCHR07NamespaceMoveFailureRollsBackRoot(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	state := filepath.Join(c.BaseConfig.ServiceStateDir, "old-demo.state")
	if err := os.WriteFile(state, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	oldRename := crudRenamePath
	sentinel := errors.New("injected namespace move failure")
	crudRenamePath = func(from, to string) error {
		if from == state {
			return sentinel
		}
		return oldRename(from, to)
	}
	t.Cleanup(func() { crudRenamePath = oldRename })
	if _, err := c.Chroots().Rename(ctx, "old", "new"); !errors.Is(err, sentinel) {
		t.Fatalf("err=%v", err)
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "old", "marker")); err != nil {
		t.Fatalf("root not rolled back: %v", err)
	}
	if _, err := os.Stat(state); err != nil {
		t.Fatalf("service namespace changed: %v", err)
	}
}

func TestCHR07ConfigMigrationFailureRollsBackBeforeRegistryCommit(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	cfgPath := filepath.Join(filepath.Dir(c.BaseConfig.DatabasePath), "config.json")
	if err := os.WriteFile(cfgPath, []byte(`{"chroot_overrides":{"old":{"locale":"pt_BR.UTF-8"}}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	c.ConfigPath = cfgPath
	c.BaseConfig.ChrootOverrides["old"] = map[string]any{"locale": "pt_BR.UTF-8"}
	oldRewrite := crudRewriteChrootOverride
	sentinel := errors.New("injected config publication failure")
	crudRewriteChrootOverride = func(string, string, string, bool) (bool, error) { return false, sentinel }
	t.Cleanup(func() { crudRewriteChrootOverride = oldRewrite })
	if _, err := c.Chroots().Rename(ctx, "old", "new"); !errors.Is(err, sentinel) {
		t.Fatalf("err=%v", err)
	}
	if row, _ := c.Registry.Get(ctx, "old"); row == nil {
		t.Fatal("old registry identity lost")
	}
	if row, _ := c.Registry.Get(ctx, "new"); row != nil {
		t.Fatal("new registry identity committed")
	}
	cfg, err := config.LoadReadOnly(cfgPath, config.WithRuntime(config.RuntimeContext{Home: t.TempDir()}))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := cfg.ChrootOverrides["old"]; !ok {
		t.Fatal("old override was lost")
	}
}

func TestCHR07RemoveCleanupFailureBecomesRecoverableDebt(t *testing.T) {
	withNoopUnmount(t)
	ctx := context.Background()
	c := prepareCRUDTarget(t, "gone")
	oldRemove := crudRemoveTree
	sentinel := errors.New("injected tombstone cleanup failure")
	crudRemoveTree = func(path string) error {
		if strings.Contains(filepath.Base(path), ".chrootctl-remove-") {
			return sentinel
		}
		return oldRemove(path)
	}
	if res, err := c.Chroots().Remove(ctx, "gone"); err != nil || !res.Removed {
		t.Fatalf("res=%+v err=%v", res, err)
	}
	crudRemoveTree = oldRemove
	t.Cleanup(func() { crudRemoveTree = oldRemove })
	pending, err := c.Registry.PendingFSMutations(ctx, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 1 || pending[0].State != registry.FSMutationCleanupDebt {
		t.Fatalf("pending=%+v", pending)
	}
	if _, err := c.Mutations.RecoverLocked(ctx, "gone"); err != nil {
		t.Fatal(err)
	}
	pending, err = c.Registry.PendingFSMutations(ctx, 0)
	if err != nil || len(pending) != 0 {
		t.Fatalf("post-recovery pending=%+v err=%v", pending, err)
	}
}

func TestCHR07RollbackConflictEscalatesToRepairRequired(t *testing.T) {
	ctx := context.Background()
	c := prepareCRUDTarget(t, "old")
	oldFn := crudRegistryRenameIdentity
	sentinel := errors.New("injected registry failure")
	crudRegistryRenameIdentity = func(*registry.Registry, context.Context, string, string, *string, string, string) error {
		if err := os.MkdirAll(filepath.Join(c.BaseConfig.ChrootRoot, "old"), 0o755); err != nil {
			return err
		}
		return sentinel
	}
	t.Cleanup(func() { crudRegistryRenameIdentity = oldFn })
	if _, err := c.Chroots().Rename(ctx, "old", "new"); err == nil {
		t.Fatal("expected rename failure")
	}
	pending, err := c.Registry.PendingFSMutations(ctx, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 1 || pending[0].State != registry.FSMutationRepairRequired {
		t.Fatalf("pending=%+v", pending)
	}
}

func TestCHR07RemoveRejectsSnapshotOutsideManagedNamespace(t *testing.T) {
	withNoopUnmount(t)
	ctx := context.Background()
	c := prepareCRUDTarget(t, "gone")
	outside := filepath.Join(filepath.Dir(c.Snapshots().Root()), "foreign-snapshot")
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Registry.AddSnapshot(ctx, registry.SnapshotInput{Name: "foreign", ChrootName: "gone", Path: outside}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Chroots().Remove(ctx, "gone"); err == nil {
		t.Fatal("split snapshot namespace was accepted")
	}
	if _, err := os.Stat(filepath.Join(c.BaseConfig.ChrootRoot, "gone", "marker")); err != nil {
		t.Fatalf("rejected remove changed root: %v", err)
	}
	if _, err := os.Stat(outside); err != nil {
		t.Fatalf("outside snapshot was changed: %v", err)
	}
	if row, _ := c.Registry.Get(ctx, "gone"); row == nil {
		t.Fatal("registry row was deleted")
	}
}
