package services

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"chrootctl/internal/fsmeta"
	"chrootctl/internal/mutation"
)

const snapshotFormatVersion = 1
const snapshotKindRootfsTarV1 = "rootfs-tar-v1"
const snapshotArchiveName = "rootfs.tar.gz"
const snapshotManifestName = "manifest.json"

type snapshotManifest struct {
	FormatVersion        int      `json:"format_version"`
	ChrootName           string   `json:"chroot_name"`
	SnapshotName         string   `json:"snapshot_name"`
	CreatedAt            string   `json:"created_at"`
	SourcePath           string   `json:"source_path"`
	Note                 string   `json:"note,omitempty"`
	ProtectedOperationID string   `json:"protected_operation_id,omitempty"`
	OperationKind        string   `json:"protected_operation_kind,omitempty"`
	MetadataContract     []string `json:"metadata_contract"`
}

func uniqueSnapshotName(prefix string) string {
	prefix = strings.Trim(strings.TrimSpace(prefix), "-")
	if prefix == "" {
		prefix = "snapshot"
	}
	buf := make([]byte, 4)
	if _, err := rand.Read(buf); err != nil {
		return fmt.Sprintf("%s-%s-%d", prefix, time.Now().UTC().Format("20060102T150405.000000000Z"), time.Now().UnixNano())
	}
	return fmt.Sprintf("%s-%s-%s", prefix, time.Now().UTC().Format("20060102T150405.000000000Z"), hex.EncodeToString(buf))
}

func snapshotMetadataContract() []string {
	return []string{"uid_gid", "mode_special_bits", "atime_mtime", "xattrs_acl_capabilities", "hardlinks", "symlinks", "fifo_device_nodes", "sparse_zero_ranges"}
}

func writeSnapshotPayload(ctx context.Context, source, stage, chrootName, snapshotName, note string) (snapshotManifest, error) {
	if err := os.MkdirAll(stage, 0o700); err != nil {
		return snapshotManifest{}, err
	}
	prov := OperationProvenanceFromContext(ctx)
	manifest := snapshotManifest{
		FormatVersion: snapshotFormatVersion, ChrootName: chrootName, SnapshotName: snapshotName,
		CreatedAt: time.Now().UTC().Format(time.RFC3339Nano), SourcePath: source, Note: note,
		ProtectedOperationID: prov.ID, OperationKind: prov.Kind, MetadataContract: snapshotMetadataContract(),
	}
	archive := filepath.Join(stage, snapshotArchiveName)
	if err := fsmeta.ArchiveTreeGzip(ctx, source, archive, fsmeta.CopyControl{}); err != nil {
		return snapshotManifest{}, err
	}
	body, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return snapshotManifest{}, err
	}
	mf, err := os.OpenFile(filepath.Join(stage, snapshotManifestName), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return snapshotManifest{}, err
	}
	if _, err = mf.Write(append(body, '\n')); err == nil {
		err = mf.Sync()
	}
	if closeErr := mf.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return snapshotManifest{}, err
	}
	if err := mutation.SyncDir(stage); err != nil {
		return snapshotManifest{}, err
	}
	return manifest, nil
}

func readSnapshotManifest(snapshotDir string) (snapshotManifest, error) {
	body, err := os.ReadFile(filepath.Join(snapshotDir, snapshotManifestName))
	if err != nil {
		return snapshotManifest{}, fmt.Errorf("read snapshot manifest: %w", err)
	}
	var m snapshotManifest
	if err := json.Unmarshal(body, &m); err != nil {
		return snapshotManifest{}, fmt.Errorf("parse snapshot manifest: %w", err)
	}
	if m.FormatVersion != snapshotFormatVersion {
		return snapshotManifest{}, fmt.Errorf("unsupported snapshot format version %d", m.FormatVersion)
	}
	if m.ChrootName == "" || m.SnapshotName == "" {
		return snapshotManifest{}, fmt.Errorf("snapshot manifest identity is incomplete")
	}
	if err := requireSnapshotMetadataContract(m.MetadataContract); err != nil {
		return snapshotManifest{}, err
	}
	if _, err := os.Stat(filepath.Join(snapshotDir, snapshotArchiveName)); err != nil {
		return snapshotManifest{}, fmt.Errorf("snapshot payload missing: %w", err)
	}
	return m, nil
}

func requireSnapshotMetadataContract(contract []string) error {
	seen := make(map[string]bool, len(contract))
	for _, feature := range contract {
		seen[strings.TrimSpace(feature)] = true
	}
	for _, required := range snapshotMetadataContract() {
		if !seen[required] {
			return fmt.Errorf("snapshot manifest is missing required metadata contract feature %q", required)
		}
	}
	return nil
}

func extractSnapshotPayload(ctx context.Context, snapshotDir, stage, expectedChroot, expectedName string) (snapshotManifest, error) {
	m, err := readSnapshotManifest(snapshotDir)
	if err != nil {
		return snapshotManifest{}, err
	}
	if m.ChrootName != expectedChroot || m.SnapshotName != expectedName {
		return snapshotManifest{}, fmt.Errorf("snapshot manifest identity mismatch: got %s/%s expected %s/%s", m.ChrootName, m.SnapshotName, expectedChroot, expectedName)
	}
	if err := fsmeta.ExtractTarGzip(ctx, filepath.Join(snapshotDir, snapshotArchiveName), stage, fsmeta.CopyControl{}); err != nil {
		return snapshotManifest{}, err
	}
	return m, nil
}

func writeSnapshotBundle(snapshotDir, target string) error {
	out, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(target)
		}
	}()
	gz := gzip.NewWriter(out)
	tw := tar.NewWriter(gz)
	for _, name := range []string{snapshotManifestName, snapshotArchiveName} {
		path := filepath.Join(snapshotDir, name)
		st, err := os.Stat(path)
		if err != nil {
			return err
		}
		h, err := tar.FileInfoHeader(st, "")
		if err != nil {
			return err
		}
		h.Name = name
		h.Mode = int64(st.Mode().Perm())
		h.Uid = 0
		h.Gid = 0
		if err := tw.WriteHeader(h); err != nil {
			return err
		}
		in, err := os.Open(path)
		if err != nil {
			return err
		}
		_, cpErr := io.Copy(tw, in)
		clErr := in.Close()
		if cpErr != nil {
			return cpErr
		}
		if clErr != nil {
			return clErr
		}
	}
	if err := tw.Close(); err != nil {
		return err
	}
	if err := gz.Close(); err != nil {
		return err
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	ok = true
	return nil
}
