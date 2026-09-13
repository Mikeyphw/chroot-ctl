package sqlitecompat

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"path/filepath"
	"sort"
	"strings"

	_ "github.com/mattn/go-sqlite3"
)

const (
	BusyTimeoutMS = 5000
	JournalMode   = "wal"
	Synchronous   = 2 // SQLite FULL
)

var requiredObjects = map[string]string{
	"artifacts":              "table",
	"chroots":                "table",
	"events":                 "table",
	"fs_mutations":           "table",
	"snapshots":              "table",
	"chroots_updated_at":     "trigger",
	"idx_artifacts_expires":  "index",
	"idx_fs_mutations_state": "index",
}

type Report struct {
	SQLiteVersion        string   `json:"sqliteVersion"`
	JournalMode          string   `json:"journalMode"`
	Synchronous          int      `json:"synchronous"`
	BusyTimeoutMS        int      `json:"busyTimeoutMs"`
	ForeignKeys          bool     `json:"foreignKeys"`
	IntegrityCheck       string   `json:"integrityCheck"`
	ForeignKeyViolations int      `json:"foreignKeyViolations"`
	Objects              []string `json:"objects"`
	SnapshotCascadeOK    bool     `json:"snapshotCascadeOk"`
}

func DSN(path string) (string, error) {
	if strings.TrimSpace(path) == "" {
		return "", errors.New("sqlite database path is empty")
	}
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", fmt.Errorf("resolve sqlite path: %w", err)
	}
	u := &url.URL{Scheme: "file", Path: filepath.ToSlash(absolute)}
	q := u.Query()
	q.Set("_busy_timeout", fmt.Sprintf("%d", BusyTimeoutMS))
	q.Set("_foreign_keys", "on")
	q.Set("_journal_mode", "WAL")
	q.Set("_synchronous", "FULL")
	q.Set("_txlock", "immediate")
	u.RawQuery = q.Encode()
	return u.String(), nil
}

func ReadOnlyDSN(path string) (string, error) {
	if strings.TrimSpace(path) == "" {
		return "", errors.New("sqlite database path is empty")
	}
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", fmt.Errorf("resolve sqlite path: %w", err)
	}
	u := &url.URL{Scheme: "file", Path: filepath.ToSlash(absolute)}
	q := u.Query()
	q.Set("mode", "ro")
	q.Set("_busy_timeout", fmt.Sprintf("%d", BusyTimeoutMS))
	q.Set("_foreign_keys", "on")
	u.RawQuery = q.Encode()
	return u.String(), nil
}

// OpenReadOnly opens an existing SQLite database without creating files,
// changing journal mode, or running schema migrations.
func OpenReadOnly(path string) (*sql.DB, error) {
	dsn, err := ReadOnlyDSN(path)
	if err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite3", dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite registry read-only: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping sqlite registry read-only: %w", err)
	}
	if _, err := db.Exec("PRAGMA query_only = ON"); err != nil {
		db.Close()
		return nil, fmt.Errorf("enable sqlite query_only: %w", err)
	}
	return db, nil
}

func Open(path string) (*sql.DB, error) {
	dsn, err := DSN(path)
	if err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite3", dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite registry: %w", err)
	}
	// The legacy Python registry serializes writers in-process and every connection
	// enables the same PRAGMAs. One Go connection keeps the compatibility spike
	// equally deterministic and avoids mixing differently configured handles.
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping sqlite registry: %w", err)
	}
	return db, nil
}

func Probe(ctx context.Context, db *sql.DB) (Report, error) {
	var report Report
	if err := db.QueryRowContext(ctx, "SELECT sqlite_version()").Scan(&report.SQLiteVersion); err != nil {
		return report, fmt.Errorf("read sqlite version: %w", err)
	}
	if err := db.QueryRowContext(ctx, "PRAGMA journal_mode").Scan(&report.JournalMode); err != nil {
		return report, fmt.Errorf("read journal_mode: %w", err)
	}
	report.JournalMode = strings.ToLower(report.JournalMode)
	if err := db.QueryRowContext(ctx, "PRAGMA synchronous").Scan(&report.Synchronous); err != nil {
		return report, fmt.Errorf("read synchronous: %w", err)
	}
	if err := db.QueryRowContext(ctx, "PRAGMA busy_timeout").Scan(&report.BusyTimeoutMS); err != nil {
		return report, fmt.Errorf("read busy_timeout: %w", err)
	}
	var foreignKeys int
	if err := db.QueryRowContext(ctx, "PRAGMA foreign_keys").Scan(&foreignKeys); err != nil {
		return report, fmt.Errorf("read foreign_keys: %w", err)
	}
	report.ForeignKeys = foreignKeys == 1
	if err := db.QueryRowContext(ctx, "PRAGMA integrity_check").Scan(&report.IntegrityCheck); err != nil {
		return report, fmt.Errorf("run integrity_check: %w", err)
	}

	rows, err := db.QueryContext(ctx, "PRAGMA foreign_key_check")
	if err != nil {
		return report, fmt.Errorf("run foreign_key_check: %w", err)
	}
	for rows.Next() {
		report.ForeignKeyViolations++
	}
	if err := rows.Close(); err != nil {
		return report, fmt.Errorf("close foreign_key_check: %w", err)
	}
	if err := rows.Err(); err != nil {
		return report, fmt.Errorf("scan foreign_key_check: %w", err)
	}

	objectRows, err := db.QueryContext(ctx, `
		SELECT type, name FROM sqlite_master
		WHERE name NOT LIKE 'sqlite_%'
		ORDER BY type, name
	`)
	if err != nil {
		return report, fmt.Errorf("list sqlite schema: %w", err)
	}
	seen := make(map[string]string)
	for objectRows.Next() {
		var typ, name string
		if err := objectRows.Scan(&typ, &name); err != nil {
			objectRows.Close()
			return report, fmt.Errorf("scan sqlite schema: %w", err)
		}
		seen[name] = typ
		report.Objects = append(report.Objects, typ+":"+name)
	}
	if err := objectRows.Close(); err != nil {
		return report, fmt.Errorf("close sqlite schema rows: %w", err)
	}
	if err := objectRows.Err(); err != nil {
		return report, fmt.Errorf("read sqlite schema rows: %w", err)
	}
	for name, typ := range requiredObjects {
		if seen[name] != typ {
			return report, fmt.Errorf("registry schema object %s must be %s, found %q", name, typ, seen[name])
		}
	}

	var fkTable, onUpdate, onDelete string
	fkRows, err := db.QueryContext(ctx, "PRAGMA foreign_key_list(snapshots)")
	if err != nil {
		return report, fmt.Errorf("read snapshots foreign keys: %w", err)
	}
	for fkRows.Next() {
		var id, seq int
		var from, to, match string
		if err := fkRows.Scan(&id, &seq, &fkTable, &from, &to, &onUpdate, &onDelete, &match); err != nil {
			fkRows.Close()
			return report, fmt.Errorf("scan snapshots foreign key: %w", err)
		}
		if fkTable == "chroots" && from == "chroot_name" && to == "name" && strings.EqualFold(onUpdate, "CASCADE") && strings.EqualFold(onDelete, "CASCADE") {
			report.SnapshotCascadeOK = true
		}
	}
	if err := fkRows.Close(); err != nil {
		return report, fmt.Errorf("close snapshots foreign keys: %w", err)
	}
	if err := fkRows.Err(); err != nil {
		return report, fmt.Errorf("read snapshots foreign keys: %w", err)
	}

	sort.Strings(report.Objects)
	if report.JournalMode != JournalMode {
		return report, fmt.Errorf("journal_mode=%s, want %s", report.JournalMode, JournalMode)
	}
	if report.Synchronous != Synchronous {
		return report, fmt.Errorf("synchronous=%d, want %d (FULL)", report.Synchronous, Synchronous)
	}
	if report.BusyTimeoutMS != BusyTimeoutMS {
		return report, fmt.Errorf("busy_timeout=%d, want %d", report.BusyTimeoutMS, BusyTimeoutMS)
	}
	if !report.ForeignKeys {
		return report, errors.New("foreign_keys is disabled")
	}
	if !strings.EqualFold(report.IntegrityCheck, "ok") {
		return report, fmt.Errorf("integrity_check=%q", report.IntegrityCheck)
	}
	if report.ForeignKeyViolations != 0 {
		return report, fmt.Errorf("foreign_key_check reported %d violation(s)", report.ForeignKeyViolations)
	}
	if !report.SnapshotCascadeOK {
		return report, errors.New("snapshots foreign key is missing ON UPDATE/DELETE CASCADE")
	}
	return report, nil
}

func MutatePythonFixture(ctx context.Context, db *sql.DB) error {
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin registry transaction: %w", err)
	}
	defer tx.Rollback()

	result, err := tx.ExecContext(ctx, `
		UPDATE chroots
		SET name = ?, path = ?, phase = ?, installed = 1, metadata_json = ?
		WHERE name = ?
	`, "go-renamed", "/data/local/tmp/go-renamed", "go02-mutated", `{"owner":"go","source":"python"}`, "python-seed")
	if err != nil {
		return fmt.Errorf("rename Python chroot row: %w", err)
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("count renamed chroot rows: %w", err)
	}
	if changed != 1 {
		return fmt.Errorf("expected one Python seed chroot, updated %d", changed)
	}

	var cascaded int
	if err := tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM snapshots WHERE chroot_name = ? AND name = ?`, "go-renamed", "python-snapshot").Scan(&cascaded); err != nil {
		return fmt.Errorf("verify snapshot update cascade: %w", err)
	}
	if cascaded != 1 {
		return errors.New("snapshot did not follow chroot rename through ON UPDATE CASCADE")
	}

	metadata, err := json.Marshal(map[string]any{"writer": "go", "roundTrip": true})
	if err != nil {
		return fmt.Errorf("encode Go metadata: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO events (event_type, actor, target, result, message, metadata_json)
		VALUES (?, ?, ?, ?, ?, ?)
	`, "go02.sqlite.mutate", "go", "go-renamed", "ok", "Go wrote through Python registry schema", string(metadata)); err != nil {
		return fmt.Errorf("insert Go audit event: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO fs_mutations
		(mutation_id, kind, target, source_path, destination_path, state, detail_json, created_at, updated_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, "go02-mutation", "rename", "go-renamed", "/data/local/tmp/python-seed", "/data/local/tmp/go-renamed", "verified", string(metadata), 2.0, 3.0); err != nil {
		return fmt.Errorf("insert Go filesystem mutation: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO artifacts
		(artifact_id, kind, path, target, size_bytes, created_at, expires_at, metadata_json)
		VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
	`, "go02-artifact", "sqlite-compat", "/data/adb/chrootctl/go02-artifact", "go-renamed", 42, 4.0, string(metadata)); err != nil {
		return fmt.Errorf("insert Go artifact: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit registry transaction: %w", err)
	}
	return nil
}
