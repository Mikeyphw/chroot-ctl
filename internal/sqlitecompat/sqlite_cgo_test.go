//go:build cgo

package sqlitecompat

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"
)

func TestProbeAndMutationMatchPythonSchema(t *testing.T) {
	path := filepath.Join(t.TempDir(), "registry.sqlite3")
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	seedSchema(t, db)
	if _, err := Probe(context.Background(), db); err != nil {
		t.Fatalf("probe: %v", err)
	}
	if err := MutatePythonFixture(context.Background(), db); err != nil {
		t.Fatalf("mutate: %v", err)
	}
	var chrootName string
	if err := db.QueryRow(`SELECT chroot_name FROM snapshots WHERE name = 'python-snapshot'`).Scan(&chrootName); err != nil {
		t.Fatal(err)
	}
	if chrootName != "go-renamed" {
		t.Fatalf("snapshot chroot_name=%q, want go-renamed", chrootName)
	}
}

func seedSchema(t *testing.T, db *sql.DB) {
	t.Helper()
	const schema = `
CREATE TABLE chroots (
 name TEXT PRIMARY KEY, distro TEXT NOT NULL, path TEXT NOT NULL, arch TEXT,
 release_name TEXT, version TEXT, phase TEXT NOT NULL, installed INTEGER NOT NULL DEFAULT 0,
 metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER chroots_updated_at AFTER UPDATE ON chroots FOR EACH ROW BEGIN
 UPDATE chroots SET updated_at = CURRENT_TIMESTAMP WHERE name = OLD.name;
END;
CREATE TABLE snapshots (
 snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, chroot_name TEXT NOT NULL,
 path TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'copy', note TEXT NOT NULL DEFAULT '',
 size_bytes INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(chroot_name, name),
 FOREIGN KEY(chroot_name) REFERENCES chroots(name) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE TABLE events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, actor TEXT NOT NULL,
 target TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT 'ok', message TEXT NOT NULL DEFAULT '',
 metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE fs_mutations (
 mutation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
 source_path TEXT NOT NULL DEFAULT '', destination_path TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
 detail_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX idx_fs_mutations_state ON fs_mutations(state, updated_at);
CREATE TABLE artifacts (
 artifact_id TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
 target TEXT NOT NULL DEFAULT '', size_bytes INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
 expires_at REAL, metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_artifacts_expires ON artifacts(expires_at);
INSERT INTO chroots(name,distro,path,arch,release_name,version,phase,installed,metadata_json)
VALUES('python-seed','ubuntu','/data/local/tmp/python-seed','arm64','noble','24.04','ready',1,'{"writer":"python"}');
INSERT INTO snapshots(name,chroot_name,path,kind,note,size_bytes,metadata_json)
VALUES('python-snapshot','python-seed','/data/adb/chrootctl/snapshots/python-seed','copy','seed',7,'{"writer":"python"}');
`
	if _, err := db.Exec(schema); err != nil {
		t.Fatalf("seed schema: %v", err)
	}
}
