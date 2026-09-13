package services

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCHR09SnapshotPayloadManifestAndRoundTrip(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("metadata-faithful snapshot fixture requires root")
	}
	root := t.TempDir()
	src := filepath.Join(root, "src")
	stage := filepath.Join(root, "snapshot")
	restore := filepath.Join(root, "restore")
	if err := os.MkdirAll(src, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "hello"), []byte("world"), 0o640); err != nil {
		t.Fatal(err)
	}
	ctx := WithOperationProvenance(context.Background(), "op-123", "chroots.upgrade")
	m, err := writeSnapshotPayload(ctx, src, stage, "work", "pre-upgrade-x", "safety")
	if err != nil {
		t.Fatal(err)
	}
	if m.ProtectedOperationID != "op-123" || m.OperationKind != "chroots.upgrade" || m.FormatVersion != snapshotFormatVersion {
		t.Fatalf("manifest=%+v", m)
	}
	if _, err := extractSnapshotPayload(context.Background(), stage, restore, "work", "pre-upgrade-x"); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(restore, "hello"))
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "world" {
		t.Fatalf("payload=%q", b)
	}
}

func TestCHR09SnapshotManifestRejectsIdentityMismatch(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("metadata-faithful snapshot fixture requires root")
	}
	root := t.TempDir()
	src := filepath.Join(root, "src")
	stage := filepath.Join(root, "snapshot")
	if err := os.MkdirAll(src, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := writeSnapshotPayload(context.Background(), src, stage, "work", "snap", "note"); err != nil {
		t.Fatal(err)
	}
	if _, err := extractSnapshotPayload(context.Background(), stage, filepath.Join(root, "restore"), "other", "snap"); err == nil {
		t.Fatal("expected identity mismatch")
	}
}

func TestCHR09SnapshotManifestRequiresMetadataContract(t *testing.T) {
	root := t.TempDir()
	manifest := snapshotManifest{
		FormatVersion: snapshotFormatVersion,
		ChrootName:    "work",
		SnapshotName:  "snap",
		CreatedAt:     "2026-09-13T00:00:00Z",
		SourcePath:    filepath.Join(root, "src"),
		MetadataContract: []string{
			"uid_gid",
			"mode_special_bits",
			"atime_mtime",
			"xattrs_acl_capabilities",
			"hardlinks",
			"symlinks",
			"fifo_device_nodes",
			// sparse_zero_ranges deliberately omitted: a rootfs snapshot that does
			// not declare the full CHR09 metadata contract must not be restored.
		},
	}
	body, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, snapshotManifestName), body, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, snapshotArchiveName), []byte("not-read-by-this-test"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err = readSnapshotManifest(root)
	if err == nil || !strings.Contains(err.Error(), "sparse_zero_ranges") {
		t.Fatalf("expected missing metadata contract feature, got %v", err)
	}
}
