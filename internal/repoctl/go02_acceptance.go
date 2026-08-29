package repoctl

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"time"

	"chrootctl/internal/sqlitecompat"
)

const (
	go02EvidenceSchema        = 1
	go02FixtureRelativePath   = "migration/contracts/v1/python-registry.sqlite3.fixture"
	ExpectedGO02FixtureSHA256 = "8be2b28573e61a5304931b9f44d03f5574016ade8aeff42dc2cf802eabc2b053"
)

type GO02DeviceEvidence struct {
	SchemaVersion     int    `json:"schemaVersion"`
	Gate              string `json:"gate"`
	GOOS              string `json:"goos"`
	GOARCH            string `json:"goarch"`
	GoVersion         string `json:"goVersion"`
	FixtureSHA256     string `json:"fixtureSha256"`
	SQLiteVersion     string `json:"sqliteVersion"`
	JournalMode       string `json:"journalMode"`
	Synchronous       int    `json:"synchronous"`
	BusyTimeoutMS     int    `json:"busyTimeoutMs"`
	ForeignKeys       bool   `json:"foreignKeys"`
	IntegrityCheck    string `json:"integrityCheck"`
	SnapshotCascadeOK bool   `json:"snapshotCascadeOk"`
	MutationVerified  bool   `json:"mutationVerified"`
	GeneratedAtUnix   int64  `json:"generatedAtUnix"`
}

func go02FixturePath(root string) string {
	return filepath.Join(root, filepath.FromSlash(go02FixtureRelativePath))
}

func regularFileSHA256(path string) (string, error) {
	st, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.Mode().IsRegular() {
		return "", fmt.Errorf("GO02 fixture/evidence must be a regular non-symlink file: %s", path)
	}
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func validateGO02Fixture(root string) (string, error) {
	path := go02FixturePath(root)
	sum, err := regularFileSHA256(path)
	if err != nil {
		return "", err
	}
	if sum != ExpectedGO02FixtureSHA256 {
		return "", fmt.Errorf("GO02 frozen Python-registry fixture drift: got %s want %s", sum, ExpectedGO02FixtureSHA256)
	}
	return path, nil
}

func executeGO02DeviceAcceptance(root string) (GO02DeviceEvidence, error) {
	if runtime.GOOS != "android" || runtime.GOARCH != "arm64" {
		return GO02DeviceEvidence{}, fmt.Errorf("GO02 device acceptance must execute as an android/arm64 Go process; current host is %s/%s", runtime.GOOS, runtime.GOARCH)
	}
	fixture, err := validateGO02Fixture(root)
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	tmp, err := os.MkdirTemp("", "chrootctl-go02-device-*")
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	defer os.RemoveAll(tmp)
	copyPath := filepath.Join(tmp, "registry.sqlite3")
	src, err := os.Open(fixture)
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	dst, err := os.OpenFile(copyPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		src.Close()
		return GO02DeviceEvidence{}, err
	}
	_, copyErr := io.Copy(dst, src)
	closeErr := dst.Close()
	src.Close()
	if copyErr != nil {
		return GO02DeviceEvidence{}, copyErr
	}
	if closeErr != nil {
		return GO02DeviceEvidence{}, closeErr
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	db, err := sqlitecompat.Open(copyPath)
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	report, err := sqlitecompat.Probe(ctx, db)
	if err == nil {
		err = sqlitecompat.MutatePythonFixture(ctx, db)
	}
	if close := db.Close(); err == nil && close != nil {
		err = close
	}
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	// Reopen with a fresh handle to prove committed compatibility state, not a
	// connection-local view, then check the rename cascade and Go-written rows.
	db, err = sqlitecompat.Open(copyPath)
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	defer db.Close()
	if _, err = sqlitecompat.Probe(ctx, db); err != nil {
		return GO02DeviceEvidence{}, err
	}
	var snapshotChroot string
	if err = db.QueryRowContext(ctx, `SELECT chroot_name FROM snapshots WHERE name='python-snapshot'`).Scan(&snapshotChroot); err != nil {
		return GO02DeviceEvidence{}, err
	}
	var eventCount, mutationCount, artifactCount int
	if err = db.QueryRowContext(ctx, `SELECT COUNT(*) FROM events WHERE event_type='go02.sqlite.mutate'`).Scan(&eventCount); err != nil {
		return GO02DeviceEvidence{}, err
	}
	if err = db.QueryRowContext(ctx, `SELECT COUNT(*) FROM fs_mutations WHERE mutation_id='go02-mutation'`).Scan(&mutationCount); err != nil {
		return GO02DeviceEvidence{}, err
	}
	if err = db.QueryRowContext(ctx, `SELECT COUNT(*) FROM artifacts WHERE artifact_id='go02-artifact'`).Scan(&artifactCount); err != nil {
		return GO02DeviceEvidence{}, err
	}
	verified := snapshotChroot == "go-renamed" && eventCount == 1 && mutationCount == 1 && artifactCount == 1
	if !verified {
		return GO02DeviceEvidence{}, fmt.Errorf("GO02 mutation verification failed after reopening registry")
	}
	return GO02DeviceEvidence{
		SchemaVersion: go02EvidenceSchema, Gate: "GO02", GOOS: runtime.GOOS, GOARCH: runtime.GOARCH,
		GoVersion: runtime.Version(), FixtureSHA256: ExpectedGO02FixtureSHA256, SQLiteVersion: report.SQLiteVersion,
		JournalMode: report.JournalMode, Synchronous: report.Synchronous, BusyTimeoutMS: report.BusyTimeoutMS,
		ForeignKeys: report.ForeignKeys, IntegrityCheck: report.IntegrityCheck, SnapshotCascadeOK: report.SnapshotCascadeOK,
		MutationVerified: true, GeneratedAtUnix: time.Now().Unix(),
	}, nil
}

func writePrivateJSON(path string, value any) error {
	if path == "" {
		return nil
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(abs), 0700); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	tmp, err := os.CreateTemp(filepath.Dir(abs), ".go02-evidence-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if err = tmp.Chmod(0600); err == nil {
		_, err = tmp.Write(raw)
	}
	if err == nil {
		err = tmp.Sync()
	}
	if closeErr := tmp.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(name, abs)
}

// RunGO02DeviceAcceptance executes the pending GO02 real-device gate and can
// persist portable evidence for a non-Android release host.
func RunGO02DeviceAcceptance(evidencePath string) (GO02DeviceEvidence, error) {
	root, err := repoRoot()
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	evidence, err := executeGO02DeviceAcceptance(root)
	if err != nil {
		return GO02DeviceEvidence{}, err
	}
	if evidencePath != "" {
		if err = writePrivateJSON(evidencePath, evidence); err != nil {
			return GO02DeviceEvidence{}, err
		}
	}
	return evidence, nil
}

func validateGO02Evidence(root, path string) error {
	if _, err := validateGO02Fixture(root); err != nil {
		return err
	}
	st, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.Mode().IsRegular() {
		return fmt.Errorf("GO02 evidence must be a regular non-symlink file")
	}
	if st.Mode().Perm()&0077 != 0 {
		return fmt.Errorf("GO02 evidence must not grant group/other permissions")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var e GO02DeviceEvidence
	if err = json.Unmarshal(raw, &e); err != nil {
		return err
	}
	if e.SchemaVersion != go02EvidenceSchema || e.Gate != "GO02" || e.GOOS != "android" || e.GOARCH != "arm64" || e.FixtureSHA256 != ExpectedGO02FixtureSHA256 || !e.MutationVerified {
		return fmt.Errorf("GO02 device evidence identity mismatch")
	}
	if e.JournalMode != sqlitecompat.JournalMode || e.Synchronous != sqlitecompat.Synchronous || e.BusyTimeoutMS != sqlitecompat.BusyTimeoutMS || !e.ForeignKeys || e.IntegrityCheck != "ok" || !e.SnapshotCascadeOK || e.SQLiteVersion == "" || e.GoVersion == "" || e.GeneratedAtUnix <= 0 {
		return fmt.Errorf("GO02 device evidence does not prove the required SQLite compatibility invariants")
	}
	return nil
}

func EnsureGO02DeviceAcceptance(root, evidencePath string) error {
	if runtime.GOOS == "android" && runtime.GOARCH == "arm64" {
		_, err := executeGO02DeviceAcceptance(root)
		return err
	}
	if evidencePath == "" {
		return fmt.Errorf("GO02 real Android/ARM64 SQLite acceptance is required; run `repoctl go02-device-acceptance --evidence <file>` on the target device and pass that file with --go02-evidence")
	}
	return validateGO02Evidence(root, evidencePath)
}
