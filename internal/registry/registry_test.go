//go:build cgo

package registry

import (
	"context"
	"database/sql"
	"errors"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"chrootctl/internal/sqlitecompat"
)

func str(value string) *string { return &value }

func openTestRegistry(t *testing.T) *Registry {
	t.Helper()
	r, err := Open(filepath.Join(t.TempDir(), "registry.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = r.Close() })
	return r
}

func TestCHR03RegistryDatabasePathMustBeAbsolute(t *testing.T) {
	if _, err := Open("relative/registry.sqlite3"); err == nil || !strings.Contains(err.Error(), "must be absolute") {
		t.Fatalf("relative registry path error = %v", err)
	}
}

func TestChrootCRUDAndSnapshotCascade(t *testing.T) {
	ctx := context.Background()
	r := openTestRegistry(t)
	if err := r.Upsert(ctx, ChrootInput{Name: "old", Distro: "ubuntu", Path: "/old", Arch: str("arm64"), Phase: "extract", Metadata: map[string]any{"nested": map[string]any{"ok": true}}}); err != nil {
		t.Fatal(err)
	}
	row, err := r.Get(ctx, "old")
	if err != nil || row == nil {
		t.Fatalf("get: %#v %v", row, err)
	}
	if row.Installed || row.Metadata["nested"] == nil {
		t.Fatalf("unexpected row: %#v", row)
	}
	snap, err := r.AddSnapshot(ctx, SnapshotInput{Name: "before", ChrootName: "old", Path: "/snap", SizeBytes: 7, Metadata: map[string]any{"writer": "go", "enabled": true}})
	if err != nil {
		t.Fatal(err)
	}
	if snap.Kind != "copy" || snap.Metadata["enabled"] != "True" {
		t.Fatalf("snapshot=%#v", snap)
	}
	newPath := "/new"
	if err := r.Rename(ctx, "old", "new", &newPath); err != nil {
		t.Fatal(err)
	}
	cascaded, err := r.GetSnapshot(ctx, snap.SnapshotID)
	if err != nil {
		t.Fatal(err)
	}
	if cascaded.ChrootName != "new" {
		t.Fatalf("cascade=%q", cascaded.ChrootName)
	}
	if err := r.Delete(ctx, "new"); err != nil {
		t.Fatal(err)
	}
	if _, err := r.GetSnapshot(ctx, snap.SnapshotID); !errors.Is(err, ErrNotFound) {
		t.Fatalf("snapshot should cascade delete: %v", err)
	}
}

func TestAtomicMutationsRollbackOnInvalidAction(t *testing.T) {
	ctx := context.Background()
	r := openTestRegistry(t)
	err := r.ApplyChrootMutations(ctx, []ChrootMutation{{Action: "upsert", Name: "first", Path: "/first"}, {Action: "bogus", Name: "second"}})
	if err == nil || !strings.Contains(err.Error(), "unsupported registry mutation action") {
		t.Fatalf("err=%v", err)
	}
	row, err := r.Get(ctx, "first")
	if err != nil {
		t.Fatal(err)
	}
	if row != nil {
		t.Fatal("transaction did not roll back")
	}
}

func TestFSMutationsArtifactsAndEvents(t *testing.T) {
	ctx := context.Background()
	r := openTestRegistry(t)
	fixed := time.Unix(1000, 0)
	r.now = func() time.Time { return fixed }
	id, err := r.BeginFSMutation(ctx, "rename", "ubuntu", "/a", "/b", map[string]any{"a": 1})
	if err != nil {
		t.Fatal(err)
	}
	if err := r.UpdateFSMutation(ctx, id, "staged", map[string]any{"b": 2}); err != nil {
		t.Fatal(err)
	}
	pending, err := r.PendingFSMutations(ctx, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 1 || pending[0].Detail["a"] != float64(1) || pending[0].Detail["b"] != float64(2) {
		t.Fatalf("pending=%#v", pending)
	}
	ttl := time.Hour
	artifact, err := r.RegisterArtifact(ctx, ArtifactInput{Path: "/tmp/a", Kind: "archive", Target: "ubuntu", SizeBytes: 42, TTL: &ttl, Metadata: map[string]any{"ok": true}})
	if err != nil {
		t.Fatal(err)
	}
	if artifact.ExpiresAt == nil || *artifact.ExpiresAt != 4600 {
		t.Fatalf("expires=%v", artifact.ExpiresAt)
	}
	fixed = time.Unix(5000, 0)
	pruned, err := r.PruneExpiredArtifacts(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(pruned) != 1 {
		t.Fatalf("pruned=%d", len(pruned))
	}
	event, err := r.AddEvent(ctx, EventInput{EventType: "test", Actor: "go", Metadata: map[string]any{"count": 3}})
	if err != nil {
		t.Fatal(err)
	}
	if event.Result != "ok" || event.Metadata["count"] != "3" {
		t.Fatalf("event=%#v", event)
	}
}

func TestCorruptJSONDoesNotBreakReads(t *testing.T) {
	ctx := context.Background()
	r := openTestRegistry(t)
	if _, err := r.db.Exec(`INSERT INTO chroots(name,distro,path,phase,metadata_json) VALUES('broken','ubuntu','/broken','ready','[')`); err != nil {
		t.Fatal(err)
	}
	row, err := r.Get(ctx, "broken")
	if err != nil {
		t.Fatal(err)
	}
	if row.Metadata["_corrupt"] != true || row.Metadata["_field"] != "chroots.metadata_json" {
		t.Fatalf("metadata=%#v", row.Metadata)
	}
}

func TestLegacySnapshotForeignKeyMigrationAndOrphanRefusal(t *testing.T) {
	t.Run("migrates", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "legacy.sqlite3")
		seedLegacy(t, path, false)
		r, err := Open(path)
		if err != nil {
			t.Fatal(err)
		}
		defer r.Close()
		report, err := sqlitecompat.Probe(context.Background(), r.db)
		if err != nil {
			t.Fatal(err)
		}
		if !report.SnapshotCascadeOK {
			t.Fatal("cascade missing")
		}
	})
	t.Run("orphans", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "orphan.sqlite3")
		seedLegacy(t, path, true)
		_, err := Open(path)
		if err == nil || !strings.Contains(err.Error(), "1 orphan snapshot row(s)") {
			t.Fatalf("err=%v", err)
		}
	})
}

func seedLegacy(t *testing.T, path string, orphan bool) {
	t.Helper()
	db, err := sqlitecompat.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	schema := strings.Replace(Schema, `FOREIGN KEY(chroot_name) REFERENCES chroots(name) ON UPDATE CASCADE ON DELETE CASCADE`, "", 1)
	// Recreate snapshots explicitly because removing the FK leaves a dangling comma in the canonical schema.
	if _, err := db.Exec(`CREATE TABLE chroots (name TEXT PRIMARY KEY,distro TEXT NOT NULL,path TEXT NOT NULL,arch TEXT,release_name TEXT,version TEXT,phase TEXT NOT NULL,installed INTEGER NOT NULL DEFAULT 0,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TRIGGER chroots_updated_at AFTER UPDATE ON chroots FOR EACH ROW BEGIN UPDATE chroots SET updated_at=CURRENT_TIMESTAMP WHERE name=OLD.name; END;
CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,chroot_name TEXT NOT NULL,path TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'copy',note TEXT NOT NULL DEFAULT '',size_bytes INTEGER NOT NULL DEFAULT 0,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(chroot_name,name));
CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,actor TEXT NOT NULL,target TEXT NOT NULL DEFAULT '',result TEXT NOT NULL DEFAULT 'ok',message TEXT NOT NULL DEFAULT '',metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE fs_mutations (mutation_id TEXT PRIMARY KEY,kind TEXT NOT NULL,target TEXT NOT NULL DEFAULT '',source_path TEXT NOT NULL DEFAULT '',destination_path TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,detail_json TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL,updated_at REAL NOT NULL);CREATE INDEX idx_fs_mutations_state ON fs_mutations(state,updated_at);
CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY,kind TEXT NOT NULL,path TEXT NOT NULL UNIQUE,target TEXT NOT NULL DEFAULT '',size_bytes INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,expires_at REAL,metadata_json TEXT NOT NULL DEFAULT '{}');CREATE INDEX idx_artifacts_expires ON artifacts(expires_at);`); err != nil {
		t.Fatal(err)
	}
	_ = schema
	if !orphan {
		if _, err := db.Exec(`INSERT INTO chroots(name,distro,path,phase) VALUES('ubuntu','ubuntu','/ubuntu','ready')`); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := db.Exec(`INSERT INTO snapshots(name,chroot_name,path) VALUES('s','ubuntu','/s')`); err != nil {
		t.Fatal(err)
	}
}

func TestCountChroots(t *testing.T) {
	path := filepath.Join(t.TempDir(), "registry.sqlite3")
	count, err := CountChroots(path)
	if err != nil || count != 0 {
		t.Fatalf("empty: %d %v", count, err)
	}
	r, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := r.Upsert(context.Background(), ChrootInput{Name: "one", Distro: "ubuntu", Path: "/one", Phase: "ready"}); err != nil {
		t.Fatal(err)
	}
	r.Close()
	count, err = CountChroots(path)
	if err != nil || count != 1 {
		t.Fatalf("count: %d %v", count, err)
	}
}

var _ *sql.DB

func TestCHR03CanonicalPathOwnershipAndRowsAffected(t *testing.T) {
	ctx := context.Background()
	r := openTestRegistry(t)
	if err := r.Upsert(ctx, ChrootInput{Name: "one", Distro: "ubuntu", Path: "/srv/../srv/one", Phase: "ready"}); err != nil {
		t.Fatal(err)
	}
	row, err := r.Get(ctx, "one")
	if err != nil {
		t.Fatal(err)
	}
	if row == nil || row.Path != "/srv/one" {
		t.Fatalf("canonical row = %#v", row)
	}
	if err := r.Upsert(ctx, ChrootInput{Name: "two", Distro: "ubuntu", Path: "/srv/one", Phase: "ready"}); err == nil || !strings.Contains(err.Error(), "does not match identity") {
		t.Fatalf("identity/ownership guard error = %v", err)
	}
	if err := r.Delete(ctx, "missing"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing delete = %v", err)
	}
}

func TestCHR03RenameRefreshesUpdatedAt(t *testing.T) {
	ctx := context.Background()
	r := openTestRegistry(t)
	if err := r.Upsert(ctx, ChrootInput{Name: "old", Distro: "ubuntu", Path: "/old", Phase: "ready"}); err != nil {
		t.Fatal(err)
	}
	before, _ := r.Get(ctx, "old")
	time.Sleep(5 * time.Millisecond)
	newPath := "/new"
	if err := r.Rename(ctx, "old", "new", &newPath); err != nil {
		t.Fatal(err)
	}
	after, err := r.Get(ctx, "new")
	if err != nil {
		t.Fatal(err)
	}
	if after == nil || before == nil || after.UpdatedAt == before.UpdatedAt {
		t.Fatalf("updated_at did not advance: before=%#v after=%#v", before, after)
	}
}

func TestCHR03SnapshotForeignKeyMustMatchExactColumns(t *testing.T) {
	path := filepath.Join(t.TempDir(), "wrong-fk.sqlite3")
	db, err := sqlitecompat.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`CREATE TABLE chroots (name TEXT PRIMARY KEY,distro TEXT NOT NULL,path TEXT NOT NULL,phase TEXT NOT NULL,installed INTEGER NOT NULL DEFAULT 0,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,chroot_name TEXT NOT NULL,owner TEXT,path TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'copy',note TEXT NOT NULL DEFAULT '',size_bytes INTEGER NOT NULL DEFAULT 0,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(chroot_name,name),FOREIGN KEY(owner) REFERENCES chroots(name) ON UPDATE CASCADE ON DELETE CASCADE);
INSERT INTO chroots(name,distro,path,phase) VALUES('ubuntu','ubuntu','/ubuntu','ready');
INSERT INTO snapshots(name,chroot_name,owner,path) VALUES('s','ubuntu','ubuntu','/s');`)
	if err != nil {
		t.Fatal(err)
	}
	_ = db.Close()
	r, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	rows, err := r.db.Query(`PRAGMA foreign_key_list(snapshots)`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	found := false
	for rows.Next() {
		var id, seq int
		var table, from, to, onUpdate, onDelete, match string
		if err := rows.Scan(&id, &seq, &table, &from, &to, &onUpdate, &onDelete, &match); err != nil {
			t.Fatal(err)
		}
		if table == "chroots" && from == "chroot_name" && to == "name" && strings.EqualFold(onUpdate, "CASCADE") && strings.EqualFold(onDelete, "CASCADE") {
			found = true
		}
	}
	if !found {
		t.Fatal("exact snapshots(chroot_name)->chroots(name) cascade FK missing after migration")
	}
}
