package services

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/redaction"
)

type SupportService struct{ C *Container }

const supportLogTailBytes = 256 * 1024

func (s *SupportService) ExportBundle(ctx context.Context, archive string, extra map[string]any) (model.SupportBundleResult, error) {
	if archive == "" {
		archive = ManagedArchive(fmt.Sprintf("chrootctl-support-%d", time.Now().UnixNano()), "tar.gz")
	}
	managedRoot := ManagedTransferRoot()
	if !s.C.DryRun {
		var err error
		managedRoot, err = EnsureManagedTransferRoot()
		if err != nil {
			return model.SupportBundleResult{}, err
		}
	}
	archive, err := filepath.Abs(archive)
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	archive, err = contained(managedRoot, archive, "support bundle artifact")
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	included := []string{"chroots.json", "host-doctor.json", "lifecycle.json", "module-runtime.json", "events.json", "operations.json", "config.json"}
	if extra != nil {
		included = append(included, "extra.json")
	}
	if _, err := os.Stat(s.C.BaseConfig.LogFile); err == nil {
		included = append(included, "chrootctl.log")
	}
	if s.C.DryRun {
		return model.SupportBundleResult{Archive: archive, Included: included, ArchiveFormat: "tar.gz", Managed: true}, nil
	}
	if err := os.MkdirAll(filepath.Dir(archive), 0o700); err != nil {
		return model.SupportBundleResult{}, err
	}
	tmp, err := os.CreateTemp(filepath.Dir(archive), "."+filepath.Base(archive)+".partial-")
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0o600); err != nil {
		_ = tmp.Close()
		return model.SupportBundleResult{}, err
	}

	hash := sha256.New()
	multi := io.MultiWriter(tmp, hash)
	gz := gzip.NewWriter(multi)
	gz.Name = filepath.Base(archive)
	gz.ModTime = time.Unix(0, 0).UTC()
	tw := tar.NewWriter(gz)
	actual := []string{}
	addBytes := func(name string, b []byte) error {
		name = filepath.Clean(name)
		if strings.HasPrefix(name, "../") || filepath.IsAbs(name) {
			return fmt.Errorf("unsafe support bundle member: %s", name)
		}
		hdr := &tar.Header{Name: name, Mode: 0o600, Size: int64(len(b)), ModTime: time.Unix(0, 0).UTC(), AccessTime: time.Unix(0, 0).UTC(), ChangeTime: time.Unix(0, 0).UTC(), Typeflag: tar.TypeReg}
		if err := tw.WriteHeader(hdr); err != nil {
			return err
		}
		if _, err := tw.Write(b); err != nil {
			return err
		}
		actual = append(actual, name)
		return nil
	}
	addJSON := func(name string, v any) error {
		safe := redaction.Value(v)
		b, e := json.MarshalIndent(safe, "", "  ")
		if e != nil {
			return fmt.Errorf("marshal %s: %w", name, e)
		}
		return addBytes(name, append(b, '\n'))
	}

	rows, err := s.C.Chroots().List(ctx)
	if err != nil {
		return model.SupportBundleResult{}, fmt.Errorf("support chroots evidence: %w", err)
	}
	if err := addJSON("chroots.json", rows); err != nil {
		return model.SupportBundleResult{}, err
	}
	if err := addJSON("host-doctor.json", s.C.System().HostDoctor(ctx)); err != nil {
		return model.SupportBundleResult{}, err
	}
	if err := addJSON("lifecycle.json", s.C.Lifecycle().Status()); err != nil {
		return model.SupportBundleResult{}, err
	}
	if err := addJSON("module-runtime.json", s.C.ModuleRuntime().Status()); err != nil {
		return model.SupportBundleResult{}, err
	}
	events, err := s.C.Audit().Recent(ctx, 200)
	if err != nil {
		return model.SupportBundleResult{}, fmt.Errorf("support audit evidence: %w", err)
	}
	if err := addJSON("events.json", events); err != nil {
		return model.SupportBundleResult{}, err
	}
	ops := []any{}
	if s.C.Operations != nil {
		if records, err := s.C.Operations.ListRecent(200, nil); err != nil {
			return model.SupportBundleResult{}, fmt.Errorf("support operation evidence: %w", err)
		} else {
			for _, r := range records {
				ops = append(ops, r)
			}
		}
	}
	if err := addJSON("operations.json", ops); err != nil {
		return model.SupportBundleResult{}, err
	}
	if err := addJSON("config.json", map[string]any{"database_path": s.C.BaseConfig.DatabasePath, "chroot_root": s.C.BaseConfig.ChrootRoot, "snapshot_dir": s.C.BaseConfig.SnapshotDir, "log_file": s.C.BaseConfig.LogFile, "service_state_dir": s.C.BaseConfig.ServiceStateDir, "service_log_dir": s.C.BaseConfig.ServiceLogDir}); err != nil {
		return model.SupportBundleResult{}, err
	}
	if extra != nil {
		if err := addJSON("extra.json", extra); err != nil {
			return model.SupportBundleResult{}, err
		}
	}
	if b, e := os.ReadFile(s.C.BaseConfig.LogFile); e == nil {
		text := redaction.String(string(b))
		if len(text) > supportLogTailBytes {
			text = text[len(text)-supportLogTailBytes:]
		}
		if err := addBytes("chrootctl.log", []byte(text)); err != nil {
			return model.SupportBundleResult{}, err
		}
	} else if !errors.Is(e, os.ErrNotExist) {
		return model.SupportBundleResult{}, fmt.Errorf("support log evidence: %w", e)
	}
	if err := tw.Close(); err != nil {
		_ = tmp.Close()
		return model.SupportBundleResult{}, err
	}
	if err := gz.Close(); err != nil {
		_ = tmp.Close()
		return model.SupportBundleResult{}, err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return model.SupportBundleResult{}, err
	}
	if err := tmp.Close(); err != nil {
		return model.SupportBundleResult{}, err
	}
	if err := os.Rename(tmpName, archive); err != nil {
		return model.SupportBundleResult{}, err
	}
	if err := mutation.SyncDir(filepath.Dir(archive)); err != nil {
		return model.SupportBundleResult{}, err
	}
	st, err := os.Stat(archive)
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	checksum := hex.EncodeToString(hash.Sum(nil))
	artifact, err := s.C.Transfer().RegisterArtifact(ctx, archive, "support-bundle", "", nil, map[string]any{"included": actual, "archive_format": "tar.gz", "checksum": checksum})
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	_, auditErr := s.C.Audit().Record(ctx, "support.bundle.export", "", "ok", "Support bundle exported", "", map[string]string{"archive": archive, "artifact_id": artifact.ArtifactID, "checksum": checksum})
	if auditErr != nil {
		return model.SupportBundleResult{}, fmt.Errorf("record support bundle audit event: %w", auditErr)
	}
	return model.SupportBundleResult{Archive: archive, Included: actual, ArtifactID: artifact.ArtifactID, ArchiveFormat: "tar.gz", Checksum: checksum, SizeBytes: st.Size(), Managed: true}, nil
}
func sanitizeText(s string) string { return strings.TrimSpace(redaction.String(s)) }
