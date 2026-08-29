package registry

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"chrootctl/internal/sqlitecompat"
)

const Schema = `
CREATE TABLE IF NOT EXISTS chroots (
    name TEXT PRIMARY KEY,
    distro TEXT NOT NULL,
    path TEXT NOT NULL,
    arch TEXT,
    release_name TEXT,
    version TEXT,
    phase TEXT NOT NULL,
    installed INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER IF NOT EXISTS chroots_updated_at
AFTER UPDATE ON chroots
FOR EACH ROW
BEGIN
    UPDATE chroots SET updated_at = CURRENT_TIMESTAMP WHERE name = OLD.name;
END;
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    chroot_name TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'copy',
    note TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chroot_name, name),
    FOREIGN KEY(chroot_name) REFERENCES chroots(name) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT 'ok',
    message TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS fs_mutations (
    mutation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    destination_path TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fs_mutations_state ON fs_mutations(state, updated_at);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    target TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    expires_at REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at);
`

var ErrNotFound = errors.New("registry record not found")

type Registry struct {
	path string
	db   *sql.DB
	mu   sync.Mutex
	now  func() time.Time
}

type Chroot struct {
	Name         string         `json:"name"`
	Distro       string         `json:"distro"`
	Path         string         `json:"path"`
	Arch         *string        `json:"arch"`
	ReleaseName  *string        `json:"release_name"`
	Version      *string        `json:"version"`
	Phase        string         `json:"phase"`
	Installed    bool           `json:"installed"`
	MetadataJSON string         `json:"metadata_json"`
	Metadata     map[string]any `json:"metadata"`
	CreatedAt    string         `json:"created_at"`
	UpdatedAt    string         `json:"updated_at"`
}

type ChrootInput struct {
	Name        string
	Distro      string
	Path        string
	Arch        *string
	ReleaseName *string
	Version     *string
	Phase       string
	Installed   bool
	Metadata    map[string]any
}

type ChrootMutation struct {
	Action      string
	Name        string
	Distro      string
	Path        string
	Arch        *string
	ReleaseName *string
	Version     *string
	Phase       string
	Installed   bool
	Metadata    map[string]any
}

type Snapshot struct {
	SnapshotID   int64             `json:"snapshot_id"`
	Name         string            `json:"name"`
	ChrootName   string            `json:"chroot_name"`
	Path         string            `json:"path"`
	Kind         string            `json:"kind"`
	Note         string            `json:"note"`
	SizeBytes    int64             `json:"size_bytes"`
	MetadataJSON string            `json:"metadata_json"`
	Metadata     map[string]string `json:"metadata"`
	CreatedAt    string            `json:"created_at"`
}

type SnapshotInput struct {
	Name       string
	ChrootName string
	Path       string
	Kind       string
	Note       string
	SizeBytes  int64
	Metadata   map[string]any
}

type FSMutation struct {
	MutationID      string         `json:"mutation_id"`
	Kind            string         `json:"kind"`
	Target          string         `json:"target"`
	SourcePath      string         `json:"source_path"`
	DestinationPath string         `json:"destination_path"`
	State           string         `json:"state"`
	DetailJSON      string         `json:"detail_json"`
	Detail          map[string]any `json:"detail"`
	CreatedAt       float64        `json:"created_at"`
	UpdatedAt       float64        `json:"updated_at"`
}

type Artifact struct {
	ArtifactID   string         `json:"artifact_id"`
	Kind         string         `json:"kind"`
	Path         string         `json:"path"`
	Target       string         `json:"target"`
	SizeBytes    int64          `json:"size_bytes"`
	CreatedAt    float64        `json:"created_at"`
	ExpiresAt    *float64       `json:"expires_at"`
	MetadataJSON string         `json:"metadata_json"`
	Metadata     map[string]any `json:"metadata"`
}

type Event struct {
	EventID      int64             `json:"event_id"`
	EventType    string            `json:"event_type"`
	Actor        string            `json:"actor"`
	Target       string            `json:"target"`
	Result       string            `json:"result"`
	Message      string            `json:"message"`
	MetadataJSON string            `json:"metadata_json"`
	Metadata     map[string]string `json:"metadata"`
	CreatedAt    string            `json:"created_at"`
}

func Open(path string) (*Registry, error) {
	if path == "" {
		return nil, errors.New("registry database path is empty")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("create registry parent: %w", err)
	}
	db, err := sqlitecompat.Open(path)
	if err != nil {
		return nil, err
	}
	r := &Registry{path: path, db: db, now: time.Now}
	if _, err := db.Exec(Schema); err != nil {
		db.Close()
		return nil, fmt.Errorf("initialize registry schema: %w", err)
	}
	if err := r.migrateSnapshotsForeignKey(context.Background()); err != nil {
		db.Close()
		return nil, err
	}
	return r, nil
}

func (r *Registry) Close() error { return r.db.Close() }
func (r *Registry) DB() *sql.DB  { return r.db }
func (r *Registry) Path() string { return r.path }

func CountChroots(path string) (int, error) {
	if _, err := os.Stat(path); errors.Is(err, os.ErrNotExist) {
		return 0, nil
	} else if err != nil {
		return 0, err
	}
	db, err := sqlitecompat.Open(path)
	if err != nil {
		return 0, err
	}
	defer db.Close()
	var count int
	if err := db.QueryRow("SELECT COUNT(*) FROM chroots").Scan(&count); err != nil {
		if isNoSuchTable(err) {
			return 0, nil
		}
		return 0, err
	}
	return count, nil
}

func isNoSuchTable(err error) bool {
	return err != nil && (strings.Contains(err.Error(), "no such table") || strings.Contains(err.Error(), "does not exist"))
}

func (r *Registry) migrateSnapshotsForeignKey(ctx context.Context) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	rows, err := r.db.QueryContext(ctx, "PRAGMA foreign_key_list(snapshots)")
	if err != nil {
		return fmt.Errorf("read snapshots foreign keys: %w", err)
	}
	cascade := false
	for rows.Next() {
		var id, seq int
		var table, from, to, onUpdate, onDelete, match string
		if err := rows.Scan(&id, &seq, &table, &from, &to, &onUpdate, &onDelete, &match); err != nil {
			rows.Close()
			return err
		}
		if table == "chroots" && onUpdate == "CASCADE" && onDelete == "CASCADE" {
			cascade = true
		}
	}
	if err := rows.Close(); err != nil {
		return err
	}
	if cascade {
		return nil
	}
	var orphanCount int
	if err := r.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM snapshots s LEFT JOIN chroots c ON c.name = s.chroot_name WHERE c.name IS NULL").Scan(&orphanCount); err != nil {
		return err
	}
	if orphanCount != 0 {
		return fmt.Errorf("registry contains %d orphan snapshot row(s); refusing to discard them while adding foreign-key integrity", orphanCount)
	}
	conn, err := r.db.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(ctx, "PRAGMA foreign_keys = OFF"); err != nil {
		return err
	}
	defer conn.ExecContext(ctx, "PRAGMA foreign_keys = ON")
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	rollback := func() { _, _ = conn.ExecContext(ctx, "ROLLBACK") }
	statements := []string{
		`CREATE TABLE snapshots_new (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            chroot_name TEXT NOT NULL,
            path TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'copy',
            note TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chroot_name, name),
            FOREIGN KEY(chroot_name) REFERENCES chroots(name) ON UPDATE CASCADE ON DELETE CASCADE
        )`,
		`INSERT INTO snapshots_new (snapshot_id,name,chroot_name,path,kind,note,size_bytes,metadata_json,created_at)
         SELECT s.snapshot_id,s.name,s.chroot_name,s.path,s.kind,s.note,s.size_bytes,s.metadata_json,s.created_at
         FROM snapshots s JOIN chroots c ON c.name=s.chroot_name`,
		`DROP TABLE snapshots`,
		`ALTER TABLE snapshots_new RENAME TO snapshots`,
	}
	for _, statement := range statements {
		if _, err := conn.ExecContext(ctx, statement); err != nil {
			rollback()
			return fmt.Errorf("migrate snapshots foreign key: %w", err)
		}
	}
	if _, err := conn.ExecContext(ctx, "COMMIT"); err != nil {
		rollback()
		return err
	}
	return nil
}

func jsonPayload(value map[string]any) (string, error) {
	if value == nil {
		value = map[string]any{}
	}
	data, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func safeJSONDict(raw, field string) map[string]any {
	decoded := map[string]any{}
	if err := json.Unmarshal([]byte(raw), &decoded); err != nil || decoded == nil {
		return map[string]any{"_corrupt": true, "_field": field}
	}
	return decoded
}

func stringifyMetadata(value map[string]any) map[string]string {
	result := make(map[string]string, len(value))
	for key, item := range value {
		result[key] = reprString(item)
	}
	return result
}

func reprString(value any) string {
	switch item := value.(type) {
	case nil:
		return "None"
	case bool:
		if item {
			return "True"
		}
		return "False"
	case string:
		return item
	case []any:
		parts := make([]string, len(item))
		for i, child := range item {
			parts[i] = reprValue(child)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		keys := make([]string, 0, len(item))
		for key := range item {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		parts := make([]string, 0, len(keys))
		for _, key := range keys {
			parts = append(parts, reprValue(key)+": "+reprValue(item[key]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	default:
		return fmt.Sprint(item)
	}
}

func reprValue(value any) string {
	if text, ok := value.(string); ok {
		return "'" + strings.ReplaceAll(text, "'", "\\'") + "'"
	}
	return reprString(value)
}

func (r *Registry) Upsert(ctx context.Context, input ChrootInput) error {
	payload, err := jsonPayload(input.Metadata)
	if err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	_, err = r.db.ExecContext(ctx, `INSERT INTO chroots (name,distro,path,arch,release_name,version,phase,installed,metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET distro=excluded.distro,path=excluded.path,arch=excluded.arch,
        release_name=excluded.release_name,version=excluded.version,phase=excluded.phase,installed=excluded.installed,metadata_json=excluded.metadata_json`,
		input.Name, input.Distro, input.Path, input.Arch, input.ReleaseName, input.Version, input.Phase, boolInt(input.Installed), payload)
	return err
}

func (r *Registry) ApplyChrootMutations(ctx context.Context, mutations []ChrootMutation) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, m := range mutations {
		if m.Name == "" {
			return errors.New("registry mutation requires name")
		}
		switch m.Action {
		case "delete":
			if _, err := tx.ExecContext(ctx, "DELETE FROM chroots WHERE name = ?", m.Name); err != nil {
				return err
			}
		case "upsert":
			distro := m.Distro
			if distro == "" {
				distro = "unknown"
			}
			phase := m.Phase
			if phase == "" {
				phase = "registered"
			}
			payload, err := jsonPayload(m.Metadata)
			if err != nil {
				return err
			}
			if _, err := tx.ExecContext(ctx, `INSERT INTO chroots (name,distro,path,arch,release_name,version,phase,installed,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET distro=excluded.distro,path=excluded.path,arch=excluded.arch,
                release_name=excluded.release_name,version=excluded.version,phase=excluded.phase,installed=excluded.installed,metadata_json=excluded.metadata_json`,
				m.Name, distro, m.Path, m.Arch, m.ReleaseName, m.Version, phase, boolInt(m.Installed), payload); err != nil {
				return err
			}
		default:
			return fmt.Errorf("unsupported registry mutation action: %s", m.Action)
		}
	}
	return tx.Commit()
}

func boolInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func scanChroot(scanner interface{ Scan(...any) error }) (Chroot, error) {
	var item Chroot
	var installed int
	err := scanner.Scan(&item.Name, &item.Distro, &item.Path, &item.Arch, &item.ReleaseName, &item.Version, &item.Phase, &installed, &item.MetadataJSON, &item.CreatedAt, &item.UpdatedAt)
	if err != nil {
		return item, err
	}
	item.Installed = installed != 0
	item.Metadata = safeJSONDict(item.MetadataJSON, "chroots.metadata_json")
	return item, nil
}

const chrootColumns = `name,distro,path,arch,release_name,version,phase,installed,metadata_json,created_at,updated_at`

func (r *Registry) Get(ctx context.Context, name string) (*Chroot, error) {
	item, err := scanChroot(r.db.QueryRowContext(ctx, "SELECT "+chrootColumns+" FROM chroots WHERE name = ?", name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}
func (r *Registry) FindByPath(ctx context.Context, path string) (*Chroot, error) {
	item, err := scanChroot(r.db.QueryRowContext(ctx, "SELECT "+chrootColumns+" FROM chroots WHERE path = ? LIMIT 1", path))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}
func (r *Registry) Rename(ctx context.Context, oldName, newName string, newPath *string) error {
	record, err := r.Get(ctx, oldName)
	if err != nil {
		return err
	}
	if record == nil {
		return fmt.Errorf("%w: %s", ErrNotFound, oldName)
	}
	path := record.Path
	if newPath != nil {
		path = *newPath
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	_, err = r.db.ExecContext(ctx, "UPDATE chroots SET name = ?, path = ? WHERE name = ?", newName, path, oldName)
	return err
}
func (r *Registry) Delete(ctx context.Context, name string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, err := r.db.ExecContext(ctx, "DELETE FROM chroots WHERE name = ?", name)
	return err
}
func (r *Registry) List(ctx context.Context) ([]Chroot, error) {
	rows, err := r.db.QueryContext(ctx, "SELECT "+chrootColumns+" FROM chroots ORDER BY name")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []Chroot
	for rows.Next() {
		item, err := scanChroot(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (r *Registry) AddSnapshot(ctx context.Context, input SnapshotInput) (Snapshot, error) {
	if input.Kind == "" {
		input.Kind = "copy"
	}
	payload, err := jsonPayload(input.Metadata)
	if err != nil {
		return Snapshot{}, err
	}
	r.mu.Lock()
	_, err = r.db.ExecContext(ctx, `INSERT INTO snapshots (name,chroot_name,path,kind,note,size_bytes,metadata_json) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(chroot_name,name) DO UPDATE SET path=excluded.path,kind=excluded.kind,note=excluded.note,size_bytes=excluded.size_bytes,metadata_json=excluded.metadata_json`,
		input.Name, input.ChrootName, input.Path, input.Kind, input.Note, input.SizeBytes, payload)
	r.mu.Unlock()
	if err != nil {
		return Snapshot{}, err
	}
	return r.GetSnapshotByName(ctx, input.ChrootName, input.Name)
}
func scanSnapshot(scanner interface{ Scan(...any) error }) (Snapshot, error) {
	var s Snapshot
	var raw string
	err := scanner.Scan(&s.SnapshotID, &s.Name, &s.ChrootName, &s.Path, &s.Kind, &s.Note, &s.SizeBytes, &raw, &s.CreatedAt)
	if err != nil {
		return s, err
	}
	s.MetadataJSON = raw
	s.Metadata = stringifyMetadata(safeJSONDict(raw, "snapshots.metadata_json"))
	return s, nil
}

const snapshotColumns = `snapshot_id,name,chroot_name,path,kind,note,size_bytes,metadata_json,created_at`

func (r *Registry) GetSnapshot(ctx context.Context, id int64) (Snapshot, error) {
	s, err := scanSnapshot(r.db.QueryRowContext(ctx, "SELECT "+snapshotColumns+" FROM snapshots WHERE snapshot_id = ?", id))
	if errors.Is(err, sql.ErrNoRows) {
		return s, fmt.Errorf("%w: snapshot %d", ErrNotFound, id)
	}
	return s, err
}
func (r *Registry) GetSnapshotByName(ctx context.Context, chroot, name string) (Snapshot, error) {
	s, err := scanSnapshot(r.db.QueryRowContext(ctx, "SELECT "+snapshotColumns+" FROM snapshots WHERE chroot_name = ? AND name = ?", chroot, name))
	if errors.Is(err, sql.ErrNoRows) {
		return s, fmt.Errorf("%w: snapshot %s/%s", ErrNotFound, chroot, name)
	}
	return s, err
}
func (r *Registry) ListSnapshots(ctx context.Context, chroot string, limit int) ([]Snapshot, error) {
	if limit <= 0 {
		limit = 100
	}
	query := "SELECT " + snapshotColumns + " FROM snapshots"
	args := []any{}
	if chroot != "" {
		query += " WHERE chroot_name = ?"
		args = append(args, chroot)
	}
	query += " ORDER BY snapshot_id DESC LIMIT ?"
	args = append(args, limit)
	rows, err := r.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Snapshot
	for rows.Next() {
		s, err := scanSnapshot(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}
func (r *Registry) DeleteSnapshot(ctx context.Context, id int64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, err := r.db.ExecContext(ctx, "DELETE FROM snapshots WHERE snapshot_id = ?", id)
	return err
}

func newID() string {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err == nil {
		return hex.EncodeToString(raw[:])
	}
	return fmt.Sprintf("%032x", uint64(time.Now().UnixNano()))
}
func (r *Registry) BeginFSMutation(ctx context.Context, kind, target, source, destination string, detail map[string]any) (string, error) {
	id := newID()
	now := float64(r.now().UnixNano()) / 1e9
	payload, err := jsonPayload(detail)
	if err != nil {
		return "", err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	_, err = r.db.ExecContext(ctx, "INSERT INTO fs_mutations (mutation_id,kind,target,source_path,destination_path,state,detail_json,created_at,updated_at) VALUES (?,?,?,?,?,'pending',?,?,?)", id, kind, target, source, destination, payload, now, now)
	return id, err
}
func (r *Registry) UpdateFSMutation(ctx context.Context, id, state string, detail map[string]any) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	var raw string
	err := r.db.QueryRowContext(ctx, "SELECT detail_json FROM fs_mutations WHERE mutation_id = ?", id).Scan(&raw)
	merged := map[string]any{}
	if err == nil {
		merged = safeJSONDict(raw, "fs_mutations.detail_json")
		if corrupt, _ := merged["_corrupt"].(bool); corrupt {
			merged = map[string]any{}
		}
	} else if !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	for k, v := range detail {
		merged[k] = v
	}
	payload, err := jsonPayload(merged)
	if err != nil {
		return err
	}
	now := float64(r.now().UnixNano()) / 1e9
	_, err = r.db.ExecContext(ctx, "UPDATE fs_mutations SET state = ?, detail_json = ?, updated_at = ? WHERE mutation_id = ?", state, payload, now, id)
	return err
}
func scanFSMutation(scanner interface{ Scan(...any) error }) (FSMutation, error) {
	var m FSMutation
	err := scanner.Scan(&m.MutationID, &m.Kind, &m.Target, &m.SourcePath, &m.DestinationPath, &m.State, &m.DetailJSON, &m.CreatedAt, &m.UpdatedAt)
	if err != nil {
		return m, err
	}
	m.Detail = safeJSONDict(m.DetailJSON, "fs_mutations.detail_json")
	return m, nil
}
func (r *Registry) PendingFSMutations(ctx context.Context, limit int) ([]FSMutation, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := r.db.QueryContext(ctx, "SELECT mutation_id,kind,target,source_path,destination_path,state,detail_json,created_at,updated_at FROM fs_mutations WHERE state IN ('pending','staged','promoting','committed') ORDER BY updated_at ASC LIMIT ?", limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []FSMutation
	for rows.Next() {
		m, err := scanFSMutation(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

type ArtifactInput struct {
	Path, Kind, Target string
	SizeBytes          int64
	TTL                *time.Duration
	NeverExpires       bool
	Metadata           map[string]any
}

func (r *Registry) RegisterArtifact(ctx context.Context, input ArtifactInput) (Artifact, error) {
	now := float64(r.now().UnixNano()) / 1e9
	ttl := 7 * 24 * time.Hour
	if input.TTL != nil {
		ttl = *input.TTL
	}
	var expires *float64
	if !input.NeverExpires {
		v := now + ttl.Seconds()
		expires = &v
	}
	payload, err := jsonPayload(input.Metadata)
	if err != nil {
		return Artifact{}, err
	}
	r.mu.Lock()
	var id string
	var created float64
	err = r.db.QueryRowContext(ctx, "SELECT artifact_id,created_at FROM artifacts WHERE path = ?", input.Path).Scan(&id, &created)
	if errors.Is(err, sql.ErrNoRows) {
		id = newID()
		created = now
		err = nil
	}
	if err == nil {
		_, err = r.db.ExecContext(ctx, `INSERT INTO artifacts (artifact_id,kind,path,target,size_bytes,created_at,expires_at,metadata_json) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,target=excluded.target,size_bytes=excluded.size_bytes,expires_at=excluded.expires_at,metadata_json=excluded.metadata_json`, id, input.Kind, input.Path, input.Target, input.SizeBytes, created, expires, payload)
	}
	r.mu.Unlock()
	if err != nil {
		return Artifact{}, err
	}
	return r.GetArtifact(ctx, id)
}
func scanArtifact(scanner interface{ Scan(...any) error }) (Artifact, error) {
	var a Artifact
	err := scanner.Scan(&a.ArtifactID, &a.Kind, &a.Path, &a.Target, &a.SizeBytes, &a.CreatedAt, &a.ExpiresAt, &a.MetadataJSON)
	if err != nil {
		return a, err
	}
	a.Metadata = safeJSONDict(a.MetadataJSON, "artifacts.metadata_json")
	return a, nil
}

const artifactColumns = `artifact_id,kind,path,target,size_bytes,created_at,expires_at,metadata_json`

func (r *Registry) GetArtifact(ctx context.Context, id string) (Artifact, error) {
	a, err := scanArtifact(r.db.QueryRowContext(ctx, "SELECT "+artifactColumns+" FROM artifacts WHERE artifact_id = ?", id))
	if errors.Is(err, sql.ErrNoRows) {
		return a, fmt.Errorf("%w: artifact %s", ErrNotFound, id)
	}
	return a, err
}
func (r *Registry) ArtifactByPath(ctx context.Context, path string) (*Artifact, error) {
	a, err := scanArtifact(r.db.QueryRowContext(ctx, "SELECT "+artifactColumns+" FROM artifacts WHERE path = ?", path))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &a, nil
}
func (r *Registry) ListArtifacts(ctx context.Context, includeExpired bool, limit int) ([]Artifact, error) {
	if limit <= 0 {
		limit = 500
	}
	query := "SELECT " + artifactColumns + " FROM artifacts"
	args := []any{}
	if !includeExpired {
		query += " WHERE expires_at IS NULL OR expires_at > ?"
		args = append(args, float64(r.now().UnixNano())/1e9)
	}
	query += " ORDER BY created_at DESC LIMIT ?"
	args = append(args, limit)
	rows, err := r.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Artifact
	for rows.Next() {
		a, err := scanArtifact(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}
func (r *Registry) DeleteArtifact(ctx context.Context, id string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, err := r.db.ExecContext(ctx, "DELETE FROM artifacts WHERE artifact_id = ?", id)
	return err
}
func (r *Registry) PruneExpiredArtifacts(ctx context.Context) ([]Artifact, error) {
	now := float64(r.now().UnixNano()) / 1e9
	r.mu.Lock()
	defer r.mu.Unlock()
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	rows, err := tx.QueryContext(ctx, "SELECT "+artifactColumns+" FROM artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", now)
	if err != nil {
		return nil, err
	}
	var out []Artifact
	for rows.Next() {
		a, err := scanArtifact(rows)
		if err != nil {
			rows.Close()
			return nil, err
		}
		out = append(out, a)
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}
	if _, err := tx.ExecContext(ctx, "DELETE FROM artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", now); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return out, nil
}

type EventInput struct {
	EventType, Actor, Target, Result, Message string
	Metadata                                  map[string]any
}

func (r *Registry) AddEvent(ctx context.Context, input EventInput) (Event, error) {
	if input.Result == "" {
		input.Result = "ok"
	}
	payload, err := jsonPayload(input.Metadata)
	if err != nil {
		return Event{}, err
	}
	r.mu.Lock()
	res, err := r.db.ExecContext(ctx, "INSERT INTO events (event_type,actor,target,result,message,metadata_json) VALUES (?,?,?,?,?,?)", input.EventType, input.Actor, input.Target, input.Result, input.Message, payload)
	r.mu.Unlock()
	if err != nil {
		return Event{}, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return Event{}, err
	}
	return r.GetEvent(ctx, id)
}
func scanEvent(scanner interface{ Scan(...any) error }) (Event, error) {
	var e Event
	err := scanner.Scan(&e.EventID, &e.EventType, &e.Actor, &e.Target, &e.Result, &e.Message, &e.MetadataJSON, &e.CreatedAt)
	if err != nil {
		return e, err
	}
	e.Metadata = stringifyMetadata(safeJSONDict(e.MetadataJSON, "events.metadata_json"))
	return e, nil
}

const eventColumns = `event_id,event_type,actor,target,result,message,metadata_json,created_at`

func (r *Registry) GetEvent(ctx context.Context, id int64) (Event, error) {
	e, err := scanEvent(r.db.QueryRowContext(ctx, "SELECT "+eventColumns+" FROM events WHERE event_id = ?", id))
	if errors.Is(err, sql.ErrNoRows) {
		return e, fmt.Errorf("%w: event %d", ErrNotFound, id)
	}
	return e, err
}
func (r *Registry) ListEvents(ctx context.Context, limit int) ([]Event, error) {
	if limit <= 0 {
		limit = 20
	}
	rows, err := r.db.QueryContext(ctx, "SELECT "+eventColumns+" FROM events ORDER BY event_id DESC LIMIT ?", limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Event
	for rows.Next() {
		e, err := scanEvent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}
