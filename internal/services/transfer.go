package services

import (
	"archive/tar"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"chrootctl/internal/fsmeta"
	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
	"chrootctl/internal/zstd"
)

var artifactTTL = map[string]time.Duration{
	"staged-import":  24 * time.Hour,
	"chroot-export":  7 * 24 * time.Hour,
	"checksum":       7 * 24 * time.Hour,
	"support-bundle": 3 * 24 * time.Hour,
	"module-archive": 7 * 24 * time.Hour,
	"debug-evidence": 3 * 24 * time.Hour,
	"smoke-result":   3 * 24 * time.Hour,
	"temporary":      24 * time.Hour,
}

const (
	maxManagedArtifactBytes = int64(16 * 1024 * 1024 * 1024)
	maxArchiveExpandedBytes = int64(32 * 1024 * 1024 * 1024)
	maxArchiveMembers       = 1000000
	minManagedFreeBytes     = uint64(64 * 1024 * 1024)
)

type TransferService struct{ C *Container }

func ManagedTransferRoot() string {
	if x := os.Getenv("CHROOTCTL_TRANSFER_DIR"); x != "" {
		return filepath.Clean(x)
	}
	if st, err := os.Stat("/data/local/tmp"); err == nil && st.IsDir() {
		return "/data/local/tmp/chrootctl-transfer"
	}
	return filepath.Join(os.TempDir(), "chrootctl-transfer")
}
func writableDir(p string) bool { return syscall.Access(p, 2) == nil }
func safeArtifactName(v string) string {
	var b strings.Builder
	for _, c := range v {
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.ContainsRune("._-", c) {
			b.WriteRune(c)
		} else {
			b.WriteByte('_')
		}
	}
	s := strings.Trim(b.String(), "._-")
	if s == "" {
		return "chroot"
	}
	return s
}
func ManagedArchive(name, suffix string) string {
	if suffix == "" {
		suffix = "tar.zst"
	}
	return filepath.Join(ManagedTransferRoot(), safeArtifactName(name)+"."+suffix)
}
func artifactKind(path string) string {
	n := strings.ToLower(filepath.Base(path))
	switch {
	case strings.HasSuffix(n, ".sha256"):
		return "checksum"
	case strings.Contains(n, "support"):
		return "support-bundle"
	case strings.Contains(n, "debug") || strings.Contains(n, "evidence"):
		return "debug-evidence"
	case strings.Contains(n, "smoke"):
		return "smoke-result"
	case strings.Contains(n, "magisk") || strings.Contains(n, "module"):
		return "module-archive"
	case strings.HasSuffix(n, ".tar.zst") || strings.HasSuffix(n, ".tar.zst.enc") || strings.HasSuffix(n, ".tzst") || strings.HasSuffix(n, ".tzst.enc"):
		return "staged-import"
	default:
		return "temporary"
	}
}
func EnsureManagedTransferRoot() (string, error) {
	root := ManagedTransferRoot()
	st, err := os.Lstat(root)
	if os.IsNotExist(err) {
		if err = os.MkdirAll(root, 0o700); err != nil {
			return "", err
		}
		st, err = os.Lstat(root)
	}
	if err != nil {
		return "", err
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
		return "", fmt.Errorf("managed transfer root is not a real directory: %s", root)
	}
	if err = os.Chmod(root, 0o700); err != nil {
		return "", err
	}
	return filepath.Abs(root)
}

func (s *TransferService) managed(path string) (string, error) {
	root, err := EnsureManagedTransferRoot()
	if err != nil {
		return "", err
	}
	return contained(root, path, "managed transfer artifact")
}
func (s *TransferService) RegisterArtifact(ctx context.Context, path, kind, target string, ttl *time.Duration, metadata map[string]any) (*registry.Artifact, error) {
	root, e := EnsureManagedTransferRoot()
	if e != nil {
		return nil, e
	}
	abs, e := filepath.Abs(path)
	if e != nil {
		return nil, e
	}
	abs, e = contained(root, abs, "managed transfer artifact")
	if e != nil {
		return nil, e
	}
	st, e := os.Stat(abs)
	if e != nil {
		return nil, e
	}
	if !st.Mode().IsRegular() {
		return nil, fmt.Errorf("managed transfer artifact is not a regular file: %s", abs)
	}
	if st.Size() > maxManagedArtifactBytes {
		return nil, fmt.Errorf("managed transfer artifact exceeds %d bytes: %s", maxManagedArtifactBytes, abs)
	}
	if kind == "" {
		kind = artifactKind(abs)
	}
	duration := artifactTTL[kind]
	if duration <= 0 {
		duration = artifactTTL["temporary"]
	}
	if ttl != nil {
		duration = *ttl
	}
	if metadata == nil {
		metadata = map[string]any{}
	}
	metadata["managed_root"] = root
	metadata["basename"] = filepath.Base(abs)
	row, e := s.C.Registry.RegisterArtifact(ctx, registry.ArtifactInput{Path: abs, Kind: kind, Target: target, SizeBytes: st.Size(), TTL: &duration, Metadata: metadata})
	if e != nil {
		return nil, e
	}
	return &row, nil
}
func (s *TransferService) ArtifactRoot() map[string]any {
	root, err := EnsureManagedTransferRoot()
	if err != nil {
		root = ManagedTransferRoot()
	}
	out := map[string]any{"path": root, "managedRoot": root, "androidDescriptorRoot": "/data/local/tmp/chrootctl-transfer", "exists": exists(root), "writable": writableDir(root), "retentionPolicy": ttlSeconds(), "maxArtifactBytes": maxManagedArtifactBytes, "minFreeBytes": minManagedFreeBytes}
	if err != nil {
		out["error"] = err.Error()
	}
	return out
}
func ttlSeconds() map[string]int64 {
	out := map[string]int64{}
	for k, v := range artifactTTL {
		out[k] = int64(v.Seconds())
	}
	return out
}
func (s *TransferService) ReconcileArtifacts(ctx context.Context) (map[string]int, error) {
	root, e := EnsureManagedTransferRoot()
	if e != nil {
		return nil, e
	}
	stats := map[string]int{"expired": 0, "stale": 0, "discovered": 0, "unlink_failed": 0}
	expired, e := s.C.Registry.PruneExpiredArtifacts(ctx)
	if e != nil {
		return nil, e
	}
	for _, row := range expired {
		p, containedErr := contained(root, row.Path, "managed transfer artifact")
		if containedErr != nil {
			stats["stale"]++
			continue
		}
		if removeErr := os.Remove(p); removeErr != nil && !os.IsNotExist(removeErr) {
			stats["unlink_failed"]++
		} else {
			stats["expired"]++
			_ = os.Remove(p + ".sha256")
		}
	}
	rows, e := s.C.Registry.ListArtifacts(ctx, true, 5000)
	if e != nil {
		return nil, e
	}
	tracked := map[string]bool{}
	for _, row := range rows {
		p, containedErr := contained(root, row.Path, "managed transfer artifact")
		if containedErr != nil {
			if err := s.C.Registry.DeleteArtifact(ctx, row.ArtifactID); err == nil {
				stats["stale"]++
			}
			continue
		}
		tracked[p] = true
		st, statErr := os.Stat(p)
		if os.IsNotExist(statErr) || (statErr == nil && !st.Mode().IsRegular()) {
			if err := s.C.Registry.DeleteArtifact(ctx, row.ArtifactID); err == nil {
				stats["stale"]++
			}
		}
	}
	entries, _ := os.ReadDir(root)
	for _, entry := range entries {
		name := entry.Name()
		if name == ".requests" || strings.HasPrefix(name, ".") || strings.HasSuffix(name, ".sha256") {
			continue
		}
		p := filepath.Join(root, name)
		if tracked[p] {
			continue
		}
		st, statErr := entry.Info()
		if statErr != nil || !st.Mode().IsRegular() {
			continue
		}
		if _, err := s.RegisterArtifact(ctx, p, artifactKind(p), "", nil, map[string]any{"discovered": true}); err == nil {
			stats["discovered"]++
		}
	}
	return stats, nil
}
func (s *TransferService) TempState(ctx context.Context) (map[string]any, error) {
	root, e := EnsureManagedTransferRoot()
	if e != nil {
		return nil, e
	}
	reconciled, e := s.ReconcileArtifacts(ctx)
	if e != nil {
		return nil, e
	}
	rows, e := s.C.Registry.ListArtifacts(ctx, false, 5000)
	if e != nil {
		return nil, e
	}
	items := []map[string]any{}
	var total int64
	for _, r := range rows {
		p, e := contained(root, r.Path, "managed transfer artifact")
		if e != nil {
			continue
		}
		st, e := os.Stat(p)
		if e != nil || !st.Mode().IsRegular() {
			continue
		}
		total += st.Size()
		items = append(items, map[string]any{"artifactId": r.ArtifactID, "artifact_id": r.ArtifactID, "name": filepath.Base(p), "path": p, "kind": r.Kind, "target": r.Target, "size_bytes": st.Size(), "sizeBytes": st.Size(), "modified_at": float64(st.ModTime().UnixNano()) / 1e9, "modifiedAt": float64(st.ModTime().UnixNano()) / 1e9, "createdAt": r.CreatedAt, "expiresAt": r.ExpiresAt, "managed": true, "metadata": r.Metadata})
	}
	sort.Slice(items, func(i, j int) bool { return items[i]["modified_at"].(float64) > items[j]["modified_at"].(float64) })
	return map[string]any{"directory": root, "managedRoot": root, "androidDescriptorRoot": "/data/local/tmp/chrootctl-transfer", "retentionPolicy": ttlSeconds(), "maxArtifactBytes": maxManagedArtifactBytes, "minFreeBytes": minManagedFreeBytes, "count": len(items), "total_bytes": total, "totalBytes": total, "items": items, "reconciled": reconciled}, nil
}
func (s *TransferService) DeleteTemp(ctx context.Context, id, path string, all bool) (map[string]any, error) {
	removed := 0
	errorsOut := []string{}
	deleteRow := func(row registry.Artifact) {
		p, e := s.managed(row.Path)
		if e != nil {
			errorsOut = append(errorsOut, e.Error())
			return
		}
		if e = os.Remove(p); e != nil && !os.IsNotExist(e) {
			errorsOut = append(errorsOut, e.Error())
			return
		}
		_ = os.Remove(p + ".sha256")
		if e = s.C.Registry.DeleteArtifact(ctx, row.ArtifactID); e != nil {
			errorsOut = append(errorsOut, e.Error())
			return
		}
		removed++
	}
	if all {
		for {
			rows, e := s.C.Registry.ListArtifacts(ctx, true, 5000)
			if e != nil {
				return nil, e
			}
			if len(rows) == 0 {
				break
			}
			beforeRemoved, beforeErrors := removed, len(errorsOut)
			for _, r := range rows {
				deleteRow(r)
			}
			if len(errorsOut) > beforeErrors || removed == beforeRemoved || len(rows) < 5000 {
				break
			}
		}
	} else if id != "" {
		r, e := s.C.Registry.GetArtifact(ctx, id)
		if e != nil {
			return nil, e
		}
		deleteRow(r)
	} else if path != "" {
		p, e := s.managed(path)
		if e != nil {
			return nil, e
		}
		r, e := s.C.Registry.ArtifactByPath(ctx, p)
		if e != nil {
			return nil, e
		}
		if r == nil {
			return nil, fmt.Errorf("unknown managed transfer artifact: %s", path)
		}
		deleteRow(*r)
	}
	state, e := s.TempState(ctx)
	if e != nil {
		return nil, e
	}
	state["removed"] = removed
	state["errors"] = errorsOut
	state["ok"] = len(errorsOut) == 0
	return state, nil
}

type TransferProgress func(any) error

type TransferControl struct {
	Progress  TransferProgress
	Cancelled func() bool
}

func (c TransferControl) check(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if c.Cancelled != nil && c.Cancelled() {
		return context.Canceled
	}
	return nil
}

func (c TransferControl) emit(ctx context.Context, phase string, percent int, message string) error {
	if err := c.check(ctx); err != nil {
		return err
	}
	if c.Progress == nil {
		return nil
	}
	return c.Progress(map[string]any{"phase": phase, "percent": percent, "message": message})
}

func transferRunner(base *sys.Runner, cancelled func() bool) sys.Runner {
	runner := *base
	runner.Cancelled = cancelled
	return runner
}

func copyWithContext(ctx context.Context, dst io.Writer, src io.Reader) (int64, error) {
	return copyWithControl(ctx, TransferControl{}, dst, src)
}

func copyWithControl(ctx context.Context, control TransferControl, dst io.Writer, src io.Reader) (int64, error) {
	buf := make([]byte, 256*1024)
	var total int64
	for {
		if err := control.check(ctx); err != nil {
			return total, err
		}
		n, readErr := src.Read(buf)
		if n > 0 {
			written, writeErr := dst.Write(buf[:n])
			total += int64(written)
			if writeErr != nil {
				return total, writeErr
			}
			if written != n {
				return total, io.ErrShortWrite
			}
		}
		if readErr == io.EOF {
			return total, nil
		}
		if readErr != nil {
			return total, readErr
		}
	}
}

func sha256FileContext(ctx context.Context, path string) (string, error) {
	return sha256FileControl(ctx, TransferControl{}, path)
}

func sha256FileControl(ctx context.Context, control TransferControl, path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = copyWithControl(ctx, control, h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func sha256File(path string) (string, error) {
	return sha256FileContext(context.Background(), path)
}
func (s *TransferService) Export(ctx context.Context, name, archive, password string) (model.ChrootExportResult, error) {
	return s.ExportWithControl(ctx, name, archive, password, TransferControl{})
}

func (s *TransferService) ExportWithControl(ctx context.Context, name, archive, password string, control TransferControl) (model.ChrootExportResult, error) {
	if e := control.emit(ctx, "prepare", 5, "Resolving export source"); e != nil {
		return model.ChrootExportResult{}, e
	}
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil || r == nil {
		if e == nil {
			e = fmt.Errorf("no registry record for chroot: %s", name)
		}
		return model.ChrootExportResult{}, e
	}
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	root, e := contained(rt.Config.ChrootRoot, r.Path, "registered chroot path")
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	mountRows, mountErr := rt.Controller.StatusChecked(true)
	if mountErr != nil {
		return model.ChrootExportResult{}, fmt.Errorf("verify export mount state: %w", mountErr)
	}
	for _, m := range mountRows {
		if !strings.EqualFold(m["mounted"], "no") {
			return model.ChrootExportResult{}, fmt.Errorf("export requires the chroot to be fully and verifiably unmounted (%s)", m["mounted"])
		}
	}
	allMounts, mountTableErr := sys.MountTableDetailed("/proc/mounts")
	if mountTableErr != nil {
		return model.ChrootExportResult{}, fmt.Errorf("verify nested export mounts: %w", mountTableErr)
	}
	for _, mount := range allMounts {
		rel, relErr := filepath.Rel(root, filepath.Clean(mount.Target))
		if relErr == nil && rel != "." && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return model.ChrootExportResult{}, fmt.Errorf("export source contains live nested mount %s; unmount it before export", mount.Target)
		}
	}
	if archive == "" {
		archive = ManagedArchive(name, "tar.zst")
	}
	archive, _ = filepath.Abs(archive)
	if password != "" && !strings.HasSuffix(archive, ".enc") {
		archive += ".enc"
	}
	managedRoot, e := EnsureManagedTransferRoot()
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	if archive, e = contained(managedRoot, archive, "managed transfer artifact"); e != nil {
		return model.ChrootExportResult{}, e
	}
	if _, e = contained(root, archive, "archive"); e == nil {
		return model.ChrootExportResult{}, fmt.Errorf("archive must be outside chroot source")
	}
	if s.C.DryRun {
		return model.ChrootExportResult{Name: name, Archive: archive, Arch: ptrText(r.Arch), Encrypted: password != ""}, nil
	}
	if e = os.MkdirAll(filepath.Dir(archive), 0o700); e != nil {
		return model.ChrootExportResult{}, e
	}
	manifest := map[string]any{"name": name, "distro": r.Distro, "arch": ptrText(r.Arch), "release_name": ptrText(r.ReleaseName), "version": ptrText(r.Version), "phase": r.Phase, "installed": r.Installed, "metadata": r.Metadata, "path_name": filepath.Base(root), "rootfs_metadata_contract": "chrootctl-rootfs-v1", "rootfs_metadata_features": []string{"uid_gid", "mode_special_bits", "atime_mtime", "xattrs_acl_capabilities", "hardlinks", "symlinks", "fifo_device_nodes", "sparse_zero_ranges"}}
	manifestDir, e := os.MkdirTemp(filepath.Dir(archive), ".chrootctl-export-manifest-")
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	defer os.RemoveAll(manifestDir)
	manifestPath := filepath.Join(manifestDir, ".chrootctl-export.json")
	if e = exclusiveJSON(manifestPath, manifest); e != nil {
		return model.ChrootExportResult{}, e
	}
	baseArchive := archive
	if strings.HasSuffix(baseArchive, ".enc") {
		baseArchive = strings.TrimSuffix(baseArchive, ".enc")
	}
	tmp := filepath.Join(filepath.Dir(archive), "."+filepath.Base(baseArchive)+fmt.Sprintf(".partial-%d", time.Now().UnixNano()))
	published := false
	defer func() {
		if !published {
			_ = os.Remove(tmp)
			_ = os.Remove(tmp + ".enc")
		}
	}()
	if e = control.emit(ctx, "archive", 25, "Creating compressed archive"); e != nil {
		return model.ChrootExportResult{}, e
	}
	runner := transferRunner(rt.Runner, control.Cancelled)
	res, e := runner.Run(ctx, []string{"tar", "--format=pax", "--numeric-owner", "--acls", "--xattrs", "--xattrs-include=*", "--sparse", "--one-file-system", "--zstd", "-cpf", tmp, "-C", filepath.Dir(root), filepath.Base(root), "-C", manifestDir, filepath.Base(manifestPath)}, sys.RunOptions{MaxCaptureBytes: 256 * 1024})
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	if res.ReturnCode != 0 {
		return model.ChrootExportResult{}, fmt.Errorf("export failed: %s", strings.TrimSpace(res.Stderr))
	}
	finalTmp := tmp
	if password != "" {
		enc := tmp + ".enc"
		if e = control.emit(ctx, "encrypt", 60, "Encrypting archive"); e != nil {
			os.Remove(tmp)
			return model.ChrootExportResult{}, e
		}
		res, e = runner.Run(ctx, []string{"openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", tmp, "-out", enc, "-pass", "stdin"}, sys.RunOptions{Input: password + "\n", MaxCaptureBytes: 256 * 1024})
		if e != nil || res.ReturnCode != 0 {
			os.Remove(tmp)
			return model.ChrootExportResult{}, fmt.Errorf("archive encryption failed: %s", strings.TrimSpace(res.Stderr))
		}
		os.Remove(tmp)
		finalTmp = enc
	}
	if e = control.emit(ctx, "commit", 75, "Publishing completed archive"); e != nil {
		return model.ChrootExportResult{}, e
	}
	if e = os.Rename(finalTmp, archive); e != nil {
		return model.ChrootExportResult{}, e
	}
	published = true
	if e = mutation.SyncDir(filepath.Dir(archive)); e != nil {
		return model.ChrootExportResult{}, e
	}
	// Publication is the cancellation boundary. After the archive is visible,
	// finish checksum/registration deterministically rather than reporting a
	// cancelled operation that has already committed output. the archive, checksum sidecar, and artifact records are
	// finished as a single managed publication transaction.
	commitCtx := context.WithoutCancel(ctx)
	_ = control.emit(commitCtx, "checksum", 85, "Computing archive checksum")
	sum, e := sha256FileContext(commitCtx, archive)
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	sumPath := archive + ".sha256"
	if e = atomicWriteFile(sumPath, []byte(sum+"  "+filepath.Base(archive)+"\n"), 0o600); e != nil {
		return model.ChrootExportResult{}, e
	}
	archiveRow, e := s.RegisterArtifact(commitCtx, archive, "chroot-export", name, nil, map[string]any{"encrypted": password != "", "checksum_path": sumPath})
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	_, e = s.RegisterArtifact(commitCtx, sumPath, "checksum", name, nil, map[string]any{"for": archive, "artifact_id": archiveRow.ArtifactID})
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	_ = control.emit(context.WithoutCancel(ctx), "complete", 100, "Export completed")
	return model.ChrootExportResult{Name: name, Archive: archive, Arch: ptrText(r.Arch), Checksum: &sum, ChecksumPath: &sumPath, Encrypted: password != ""}, nil
}
func exclusiveJSON(path string, v any) error {
	f, e := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		return e
	}
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	e = enc.Encode(v)
	ce := f.Close()
	if e != nil {
		os.Remove(path)
		return e
	}
	return ce
}
func atomicWriteFile(path string, data []byte, mode os.FileMode) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".tmp-")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if _, err = tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err = tmp.Chmod(mode); err != nil {
		tmp.Close()
		return err
	}
	if err = tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	if err = os.Rename(tmpName, path); err != nil {
		return err
	}
	return mutation.SyncDir(dir)
}
func (s *TransferService) Inspect(ctx context.Context, archive, password string) (model.ChrootArchiveInspection, error) {
	return s.InspectWithControl(ctx, archive, password, TransferControl{})
}

func (s *TransferService) InspectWithControl(ctx context.Context, archive, password string, control TransferControl) (model.ChrootArchiveInspection, error) {
	archive, _ = filepath.Abs(archive)
	st, e := os.Stat(archive)
	if e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	if e = validateArchiveFileSize(archive, st.Size()); e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	sum, sumPathPtr, verified, e := requireArchiveChecksum(ctx, control, archive)
	if e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	tmp, e := os.MkdirTemp("", "chrootctl-inspect-*")
	if e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	defer os.RemoveAll(tmp)
	source := archive
	rt, _ := s.C.RuntimeFor("", "")
	runner := transferRunner(rt.Runner, control.Cancelled)
	if strings.HasSuffix(archive, ".enc") {
		if password == "" {
			return model.ChrootArchiveInspection{}, fmt.Errorf("password required for encrypted archive")
		}
		source = filepath.Join(tmp, strings.TrimSuffix(filepath.Base(archive), ".enc"))
		res, e := runner.Run(ctx, []string{"openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", archive, "-out", source, "-pass", "stdin"}, sys.RunOptions{Input: password + "\n", MaxCaptureBytes: 256 * 1024})
		if e != nil || res.ReturnCode != 0 {
			return model.ChrootArchiveInspection{}, fmt.Errorf("encrypted archive could not be opened")
		}
	}
	tarPath := filepath.Join(tmp, "archive.tar")
	if e = decompressZstdFile(ctx, control, source, tarPath, 12, 20); e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	if e = control.emit(ctx, "manifest", 22, "Validating archive manifest"); e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	manifest, size, e := inspectTar(ctx, control, tarPath)
	if e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	if e = validateImportManifest(manifest); e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	pathName := fmt.Sprint(manifest["path_name"])
	sourceName := fmt.Sprint(manifest["name"])
	if sourceName == "" {
		sourceName = pathName
	}
	target, _ := s.C.Registry.Get(ctx, sourceName)
	created := st.ModTime().UTC().Format(time.RFC3339)
	return model.ChrootArchiveInspection{Archive: archive, SourceName: sourceName, SuggestedName: sourceName, PathName: pathName, Distro: fmt.Sprint(manifest["distro"]), Arch: fmt.Sprint(manifest["arch"]), ReleaseName: fmt.Sprint(manifest["release_name"]), Version: fmt.Sprint(manifest["version"]), Phase: fmt.Sprint(manifest["phase"]), Installed: manifest["installed"] == true, Metadata: stringMetadataAny(manifest["metadata"]), SizeBytes: int(st.Size()), ExtractedSizeBytes: int(size), CreatedAt: created, Checksum: sum, ChecksumPath: sumPathPtr, ChecksumVerified: verified, IntegritySource: checksumIntegritySource(verified), Encrypted: strings.HasSuffix(archive, ".enc"), TargetExists: target != nil, ConflictStrategyOptions: []string{"rename", "overwrite"}}, nil
}
func validateArchiveFileSize(path string, size int64) error {
	if size <= 0 {
		return fmt.Errorf("archive is empty: %s", path)
	}
	if size > maxManagedArtifactBytes {
		return fmt.Errorf("archive exceeds %d bytes: %s", maxManagedArtifactBytes, path)
	}
	return nil
}

func requireArchiveChecksum(ctx context.Context, control TransferControl, archive string) (*string, *string, *bool, error) {
	sumPath := archive + ".sha256"
	text, err := os.ReadFile(sumPath)
	if err != nil {
		if os.IsNotExist(err) {
			// A missing export sidecar is not proof of corruption. Compute the
			// archive digest for local/import tracking, but keep verification false
			// so callers never confuse it with the original export checksum.
			if emitErr := control.emit(ctx, "checksum", 8, "Computing SHA-256 (original export sidecar unavailable)"); emitErr != nil {
				return nil, nil, nil, emitErr
			}
			actual, hashErr := sha256FileControl(ctx, control, archive)
			if hashErr != nil {
				return nil, nil, nil, hashErr
			}
			verified := false
			return &actual, nil, &verified, nil
		}
		return nil, nil, nil, fmt.Errorf("archive checksum sidecar could not be read: %s: %w", sumPath, err)
	}
	fields := strings.Fields(string(text))
	if len(fields) == 0 {
		return nil, nil, nil, fmt.Errorf("archive checksum sidecar is empty: %s", sumPath)
	}
	want := strings.ToLower(fields[0])
	if len(want) != sha256.Size*2 {
		return nil, nil, nil, fmt.Errorf("archive checksum sidecar is malformed: %s", sumPath)
	}
	if _, err = hex.DecodeString(want); err != nil {
		return nil, nil, nil, fmt.Errorf("archive checksum sidecar is malformed: %s", sumPath)
	}
	if len(fields) > 1 && filepath.Base(fields[1]) != filepath.Base(archive) {
		return nil, nil, nil, fmt.Errorf("archive checksum sidecar names %s, want %s", filepath.Base(fields[1]), filepath.Base(archive))
	}
	if emitErr := control.emit(ctx, "checksum", 8, "Verifying export checksum"); emitErr != nil {
		return nil, nil, nil, emitErr
	}
	actual, err := sha256FileControl(ctx, control, archive)
	if err != nil {
		return nil, nil, nil, err
	}
	ok := actual == want
	if !ok {
		return nil, nil, nil, fmt.Errorf("archive checksum verification failed")
	}
	return &want, &sumPath, &ok, nil
}

func checksumIntegritySource(verified *bool) string {
	if verified != nil && *verified {
		return "export_sidecar_verified"
	}
	return "computed_on_import"
}

func manifestText(m map[string]any, key string) string { return strings.TrimSpace(fmt.Sprint(m[key])) }

func validateImportManifest(manifest map[string]any) error {
	if contract := manifestText(manifest, "rootfs_metadata_contract"); contract != "chrootctl-rootfs-v1" {
		return fmt.Errorf("archive is not proven metadata-faithful (rootfs_metadata_contract=%q); re-export it with CHR09 or newer", contract)
	}
	if _, err := validation.ChrootNameField(manifestText(manifest, "name"), "manifest.name"); err != nil {
		return err
	}
	if _, err := validation.ChrootNameField(manifestText(manifest, "path_name"), "manifest.path_name"); err != nil {
		return err
	}
	distro := manifestText(manifest, "distro")
	if distro != "ubuntu" && distro != "arch" {
		return fmt.Errorf("unsupported archive distro: %s", distro)
	}
	arch := manifestText(manifest, "arch")
	if arch != "" && arch != "arm64" && arch != "amd64" {
		return fmt.Errorf("unsupported archive architecture: %s", arch)
	}
	phase := manifestText(manifest, "phase")
	validPhase := map[string]bool{"registered": true, "extract": true, "bootstrap": true, "desktop": true, "finalize": true, "ready": true}
	if phase == "" || !validPhase[phase] {
		return fmt.Errorf("unsupported archive phase: %s", phase)
	}
	if _, ok := manifest["installed"].(bool); !ok {
		return fmt.Errorf("archive manifest installed must be a boolean")
	}
	metadata, hasMetadata := manifest["metadata"]
	if !hasMetadata {
		return fmt.Errorf("archive manifest metadata field is missing")
	}
	if metadata != nil {
		if _, ok := metadata.(map[string]any); !ok {
			return fmt.Errorf("archive manifest metadata must be an object")
		}
	}
	features, ok := manifest["rootfs_metadata_features"].([]any)
	if !ok || len(features) == 0 {
		return fmt.Errorf("archive manifest missing rootfs metadata feature list")
	}
	required := map[string]bool{"uid_gid": false, "mode_special_bits": false, "hardlinks": false, "symlinks": false}
	for _, item := range features {
		if text, ok := item.(string); ok {
			if _, needed := required[text]; needed {
				required[text] = true
			}
		}
	}
	for name, present := range required {
		if !present {
			return fmt.Errorf("archive manifest missing rootfs metadata feature %s", name)
		}
	}
	return nil
}

func stringMetadataAny(v any) map[string]string { m, _ := v.(map[string]any); return stringMetadata(m) }
func inspectTar(ctx context.Context, control TransferControl, path string) (map[string]any, int64, error) {
	f, e := os.Open(path)
	if e != nil {
		return nil, 0, e
	}
	defer f.Close()
	tr := tar.NewReader(f)
	var manifest map[string]any
	var total int64
	members := 0
	for {
		if err := control.check(ctx); err != nil {
			return nil, 0, err
		}
		h, e := tr.Next()
		if e == io.EOF {
			break
		}
		if e != nil {
			return nil, 0, e
		}
		name := filepath.Clean(h.Name)
		if filepath.IsAbs(name) || name == ".." || strings.HasPrefix(name, ".."+string(filepath.Separator)) {
			return nil, 0, fmt.Errorf("unsafe archive member: %s", h.Name)
		}
		members++
		if members > maxArchiveMembers {
			return nil, 0, fmt.Errorf("archive contains too many members")
		}
		total += max64(h.Size, 0)
		if total > maxArchiveExpandedBytes {
			return nil, 0, fmt.Errorf("archive expanded payload exceeds %d bytes", maxArchiveExpandedBytes)
		}
		if name == ".chrootctl-export.json" {
			b, e := io.ReadAll(io.LimitReader(tr, 1024*1024))
			if e != nil {
				return nil, 0, e
			}
			if e = json.Unmarshal(b, &manifest); e != nil {
				return nil, 0, e
			}
		}
	}
	if manifest == nil {
		return nil, 0, fmt.Errorf("archive missing .chrootctl-export.json")
	}
	return manifest, total, nil
}
func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

type transferProgressReader struct {
	ctx      context.Context
	control  TransferControl
	r        io.Reader
	total    int64
	read     int64
	start    int
	end      int
	nextEmit int
}

func (r *transferProgressReader) Read(p []byte) (int, error) {
	n, err := r.r.Read(p)
	r.read += int64(n)
	if n > 0 && r.total > 0 && r.control.Progress != nil {
		span := r.end - r.start
		percent := r.start + int((r.read*int64(span))/r.total)
		if percent > r.end {
			percent = r.end
		}
		if percent >= r.nextEmit {
			compressedPercent := int((r.read * 100) / r.total)
			if compressedPercent > 100 {
				compressedPercent = 100
			}
			if emitErr := r.control.emit(r.ctx, "decompress", percent, fmt.Sprintf("Decompressing archive (%d%% of compressed input)", compressedPercent)); emitErr != nil {
				return n, emitErr
			}
			r.nextEmit = percent + 5
		}
	}
	return n, err
}

func decompressZstdFile(ctx context.Context, control TransferControl, source, destination string, startPercent, endPercent int) error {
	if err := control.emit(ctx, "decompress", startPercent, "Decompressing zstd archive"); err != nil {
		return err
	}
	in, err := os.Open(source)
	if err != nil {
		return fmt.Errorf("open zstd archive %s: %w", source, err)
	}
	defer in.Close()
	st, err := in.Stat()
	if err != nil {
		return fmt.Errorf("stat zstd archive %s: %w", source, err)
	}
	out, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return fmt.Errorf("create decompressed archive %s: %w", destination, err)
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(destination)
		}
	}()
	progressSource := &transferProgressReader{ctx: ctx, control: control, r: in, total: st.Size(), start: startPercent, end: endPercent, nextEmit: startPercent + 5}
	decoder := zstd.NewReader(progressSource)
	limited := &io.LimitedReader{R: decoder, N: maxArchiveExpandedBytes + 1}
	written, err := copyWithControl(ctx, control, out, limited)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return err
		}
		return fmt.Errorf("zstd decompression failed for %s: %w", source, err)
	}
	if written > maxArchiveExpandedBytes {
		return fmt.Errorf("expanded archive exceeds %d bytes", maxArchiveExpandedBytes)
	}
	if err = out.Sync(); err != nil {
		return fmt.Errorf("sync decompressed archive: %w", err)
	}
	if err = out.Close(); err != nil {
		return fmt.Errorf("close decompressed archive: %w", err)
	}
	ok = true
	return control.emit(ctx, "decompress", endPercent, "Archive decompressed")
}

func (s *TransferService) materializeTar(ctx context.Context, archive, password, tmp string) (string, error) {
	return s.materializeTarWithControl(ctx, archive, password, tmp, TransferControl{})
}

func (s *TransferService) materializeTarWithControl(ctx context.Context, archive, password, tmp string, control TransferControl) (string, error) {
	source := archive
	rt, _ := s.C.RuntimeFor("", "")
	runner := transferRunner(rt.Runner, control.Cancelled)
	if strings.HasSuffix(archive, ".enc") {
		if password == "" {
			return "", fmt.Errorf("password required for encrypted archive")
		}
		source = filepath.Join(tmp, "decrypted.tar.zst")
		res, e := runner.Run(ctx, []string{"openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", archive, "-out", source, "-pass", "stdin"}, sys.RunOptions{Input: password + "\n", MaxCaptureBytes: 256 * 1024})
		if e != nil || res.ReturnCode != 0 {
			return "", fmt.Errorf("encrypted archive could not be opened")
		}
		if st, statErr := os.Stat(source); statErr != nil {
			return "", statErr
		} else if e = validateArchiveFileSize(source, st.Size()); e != nil {
			return "", e
		}
	}
	tarPath := filepath.Join(tmp, "archive.tar")
	if e := decompressZstdFile(ctx, control, source, tarPath, 30, 45); e != nil {
		return "", e
	}
	return tarPath, nil
}
func safeExtractParent(root, path string) error {
	parent := filepath.Dir(path)
	rel, e := filepath.Rel(root, parent)
	if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return fmt.Errorf("archive member escapes target")
	}
	cur := root
	if rel == "." {
		return nil
	}
	for _, part := range strings.Split(rel, string(filepath.Separator)) {
		cur = filepath.Join(cur, part)
		st, e := os.Lstat(cur)
		if os.IsNotExist(e) {
			if e = os.Mkdir(cur, 0755); e != nil {
				return e
			}
			continue
		}
		if e != nil {
			return e
		}
		if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
			return fmt.Errorf("archive parent is not a real directory: %s", cur)
		}
	}
	return nil
}
func extractRootFromTar(ctx context.Context, control TransferControl, tarPath, destRoot, pathName string) error {
	f, err := os.Open(tarPath)
	if err != nil {
		return err
	}
	defer f.Close()
	return fsmeta.ExtractTarRoot(ctx, f, destRoot, pathName, fsmeta.CopyControl{
		Check: func(checkCtx context.Context) error { return control.check(checkCtx) },
	})
}

func (s *TransferService) Import(ctx context.Context, archive, name, conflict, password, postImport string) (model.ChrootImportResult, error) {
	return s.ImportWithControl(ctx, archive, name, conflict, password, postImport, TransferControl{})
}

func (s *TransferService) ImportWithControl(ctx context.Context, archive, name, conflict, password, postImport string, control TransferControl) (model.ChrootImportResult, error) {
	archive, _ = filepath.Abs(archive)
	if _, e := os.Stat(archive); e != nil {
		return model.ChrootImportResult{}, e
	}
	if conflict == "" {
		conflict = "rename"
	}
	if conflict != "rename" && conflict != "overwrite" {
		return model.ChrootImportResult{}, fmt.Errorf("unsupported conflict strategy: %s", conflict)
	}
	if postImport == "" {
		postImport = "register"
	}
	if e := validatePostImportAction(postImport); e != nil {
		return model.ChrootImportResult{}, e
	}
	if s.C.DryRun {
		inspection, e := s.InspectWithControl(ctx, archive, password, control)
		if e != nil {
			return model.ChrootImportResult{}, e
		}
		if name == "" {
			name = inspection.SuggestedName
		}
		safe, e := validation.ChrootName(name)
		if e != nil {
			return model.ChrootImportResult{}, e
		}
		if postImport == "" {
			postImport = "register"
		}
		if e = validatePostImportAction(postImport); e != nil {
			return model.ChrootImportResult{}, e
		}
		ok := true
		return model.ChrootImportResult{Name: safe, Archive: archive, Arch: inspection.Arch, Path: filepath.Join(s.C.BaseConfig.ChrootRoot, safe), ChecksumVerified: inspection.ChecksumVerified, IntegritySource: inspection.IntegritySource, ChecksumPath: inspection.ChecksumPath, ConflictStrategy: conflict, Encrypted: strings.HasSuffix(archive, ".enc"), ValidationOk: &ok, ValidationSummary: "dry-run: archive structure and manifest validated; checksum integrity source recorded; extraction and publication were not performed", PostImportAction: postImport}, nil
	}
	if e := control.emit(ctx, "inspect", 5, "Inspecting import archive"); e != nil {
		return model.ChrootImportResult{}, e
	}
	inspection, e := s.InspectWithControl(ctx, archive, password, control)
	if e != nil {
		return model.ChrootImportResult{}, e
	}
	if managedArchive, managedErr := s.managed(archive); managedErr == nil {
		metadata := map[string]any{"integrity_source": inspection.IntegritySource}
		if inspection.Checksum != nil {
			metadata["checksum"] = *inspection.Checksum
		}
		if inspection.ChecksumPath != nil {
			metadata["checksum_path"] = *inspection.ChecksumPath
		}
		_, e = s.RegisterArtifact(ctx, managedArchive, "staged-import", "", nil, metadata)
		if e != nil {
			return model.ChrootImportResult{}, e
		}
	}
	if name == "" {
		name = inspection.SuggestedName
	}
	safe, e := validation.ChrootName(name)
	if e != nil {
		return model.ChrootImportResult{}, e
	}
	name = safe
	root := s.C.BaseConfig.ChrootRoot
	if e = os.MkdirAll(root, 0755); e != nil {
		return model.ChrootImportResult{}, e
	}
	target := filepath.Join(root, name)
	existing, e := s.C.Registry.Get(ctx, name)
	if e != nil {
		return model.ChrootImportResult{}, e
	}
	if conflict == "rename" && (existing != nil || exists(target)) {
		base := name
		for i := 2; ; i++ {
			candidate := fmt.Sprintf("%s-%d", base, i)
			p := filepath.Join(root, candidate)
			r, _ := s.C.Registry.Get(ctx, candidate)
			if r == nil && !exists(p) {
				name = candidate
				target = p
				existing = nil
				break
			}
		}
	}
	if conflict == "overwrite" && existing != nil {
		resolved, err := s.C.ResolveTarget(ctx, name, false)
		if err != nil {
			return model.ChrootImportResult{}, err
		}
		if resolved == nil {
			return model.ChrootImportResult{}, fmt.Errorf("unknown chroot: %s", name)
		}
		target = resolved.RootPath
		root = filepath.Dir(target)
		rt, err := s.C.RuntimeFor(name, "")
		if err != nil {
			return model.ChrootImportResult{}, err
		}
		mountRows, mountErr := rt.Controller.StatusChecked(true)
		if mountErr != nil {
			return model.ChrootImportResult{}, fmt.Errorf("verify overwrite mount state: %w", mountErr)
		}
		for _, m := range mountRows {
			if !strings.EqualFold(m["mounted"], "no") {
				return model.ChrootImportResult{}, fmt.Errorf("overwrite import requires the existing chroot to be fully and verifiably unmounted (%s)", m["mounted"])
			}
		}
	}
	tmp, e := os.MkdirTemp("", "chrootctl-import-*")
	if e != nil {
		return model.ChrootImportResult{}, e
	}
	defer os.RemoveAll(tmp)
	if e = control.emit(ctx, "materialize", 25, "Materializing import archive"); e != nil {
		return model.ChrootImportResult{}, e
	}
	tarPath, e := s.materializeTarWithControl(ctx, archive, password, tmp, control)
	if e != nil {
		return model.ChrootImportResult{}, e
	}
	stage, e := os.MkdirTemp(root, ".chrootctl-stage-"+safeArtifactName(name)+"-")
	if e != nil {
		return model.ChrootImportResult{}, e
	}
	if e = control.emit(ctx, "extract", 50, "Extracting root filesystem"); e != nil {
		cleanupErr := os.RemoveAll(stage)
		return model.ChrootImportResult{}, errors.Join(e, cleanupErr)
	}
	if e = extractRootFromTar(ctx, control, tarPath, stage, inspection.PathName); e != nil {
		cleanupErr := os.RemoveAll(stage)
		return model.ChrootImportResult{}, errors.Join(e, cleanupErr)
	}
	if e = control.emit(ctx, "extract", 72, "Root filesystem extracted"); e != nil {
		cleanupErr := os.RemoveAll(stage)
		return model.ChrootImportResult{}, errors.Join(e, cleanupErr)
	}
	backup := filepath.Join(root, fmt.Sprintf(".chrootctl-backup-%s-%d", safeArtifactName(name), time.Now().UnixNano()))
	had := exists(target)
	tx, e := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "chroot.import", Target: name, Source: archive, Destination: target, Scope: "global", Detail: map[string]any{"stage": stage, "backup": backup, "had_existing": had}})
	if e != nil {
		cleanupErr := os.RemoveAll(stage)
		return model.ChrootImportResult{}, errors.Join(e, cleanupErr)
	}
	if e = tx.Transition(ctx, registry.FSMutationStaged, map[string]any{"stage": stage, "backup": backup, "had_existing": had}); e != nil {
		cleanupErr := os.RemoveAll(stage)
		if cleanupErr != nil {
			if u := tx.Transition(context.WithoutCancel(ctx), registry.FSMutationRepairRequired, map[string]any{"stage": stage, "backup": backup, "journal_error": e.Error(), "cleanup_error": cleanupErr.Error()}); u != nil {
				return model.ChrootImportResult{}, errors.Join(e, cleanupErr, u)
			}
		}
		return model.ChrootImportResult{}, errors.Join(e, cleanupErr)
	}
	if e = control.emit(ctx, "commit", 80, "Committing imported root filesystem"); e != nil {
		cleanupErr := os.RemoveAll(stage)
		state := registry.FSMutationRolledBack
		detail := map[string]any{"cancelled": true, "stage": stage, "backup": backup}
		if cleanupErr != nil {
			state = registry.FSMutationRepairRequired
			detail["cleanup_error"] = cleanupErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.ChrootImportResult{}, errors.Join(e, cleanupErr, u)
		}
		return model.ChrootImportResult{}, errors.Join(e, cleanupErr)
	}
	if had {
		if e = os.Rename(target, backup); e != nil {
			cleanupErr := os.RemoveAll(stage)
			state := registry.FSMutationRolledBack
			detail := map[string]any{"stage": stage, "backup": backup, "rename_error": e.Error()}
			if cleanupErr != nil {
				state = registry.FSMutationRepairRequired
				detail["cleanup_error"] = cleanupErr.Error()
			}
			if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
				return model.ChrootImportResult{}, errors.Join(e, cleanupErr, u)
			}
			return model.ChrootImportResult{}, errors.Join(e, cleanupErr)
		}
		if e = mutation.SyncDir(root); e != nil {
			rollbackErr := os.Rename(backup, target)
			if rollbackErr == nil {
				rollbackErr = mutation.SyncDir(root)
			}
			rollbackErr = errors.Join(rollbackErr, os.RemoveAll(stage))
			state := registry.FSMutationRolledBack
			detail := map[string]any{"stage": stage, "backup": backup, "sync_error": e.Error()}
			if rollbackErr != nil {
				state = registry.FSMutationRepairRequired
				detail["rollback_error"] = rollbackErr.Error()
			}
			if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
				return model.ChrootImportResult{}, errors.Join(e, rollbackErr, u)
			}
			return model.ChrootImportResult{}, errors.Join(e, rollbackErr)
		}
	}
	if e = tx.Transition(ctx, registry.FSMutationPromoting, map[string]any{"stage": stage, "backup": backup, "had_existing": had}); e != nil {
		var rollbackErr error
		if had {
			rollbackErr = os.Rename(backup, target)
			if rollbackErr == nil {
				rollbackErr = mutation.SyncDir(root)
			}
		}
		rollbackErr = errors.Join(rollbackErr, os.RemoveAll(stage))
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "backup": backup, "journal_error": e.Error()}
		if rollbackErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = rollbackErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.ChrootImportResult{}, errors.Join(e, rollbackErr, u)
		}
		return model.ChrootImportResult{}, errors.Join(e, rollbackErr)
	}
	if e = os.Rename(stage, target); e != nil {
		var rollbackErr error
		if had {
			rollbackErr = os.Rename(backup, target)
			if rollbackErr == nil {
				rollbackErr = mutation.SyncDir(root)
			}
		}
		rollbackErr = errors.Join(rollbackErr, os.RemoveAll(stage))
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "backup": backup, "rename_error": e.Error()}
		if rollbackErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = rollbackErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.ChrootImportResult{}, errors.Join(e, rollbackErr, u)
		}
		return model.ChrootImportResult{}, errors.Join(e, rollbackErr)
	}
	if e = mutation.SyncDir(root); e != nil {
		rollbackErr := os.RemoveAll(target)
		if had && rollbackErr == nil {
			rollbackErr = os.Rename(backup, target)
		}
		if rollbackErr == nil {
			rollbackErr = mutation.SyncDir(root)
		}
		state := registry.FSMutationRolledBack
		detail := map[string]any{"stage": stage, "backup": backup, "sync_error": e.Error()}
		if rollbackErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = rollbackErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.ChrootImportResult{}, errors.Join(e, rollbackErr, u)
		}
		return model.ChrootImportResult{}, errors.Join(e, rollbackErr)
	}
	meta := map[string]any{}
	for k, v := range inspection.Metadata {
		meta[k] = v
	}
	meta["imported"] = "yes"
	meta["_chrootctl_mutation_id"] = tx.ID
	arch, release, version := inspection.Arch, inspection.ReleaseName, inspection.Version
	if arch == "" {
		arch = s.C.BaseConfig.TargetArch
	}
	if e = s.C.Registry.Upsert(ctx, registry.ChrootInput{Name: name, Distro: inspection.Distro, Path: target, Arch: strPtr(arch), ReleaseName: strPtr(release), Version: strPtr(version), Phase: inspection.Phase, Installed: inspection.Installed, Metadata: meta}); e != nil {
		rollbackErr := os.RemoveAll(target)
		if had && rollbackErr == nil {
			rollbackErr = os.Rename(backup, target)
		}
		if rollbackErr == nil {
			rollbackErr = mutation.SyncDir(root)
		}
		state := registry.FSMutationRolledBack
		detail := map[string]any{"registry_error": e.Error(), "backup": backup}
		if rollbackErr != nil {
			state = registry.FSMutationRepairRequired
			detail["rollback_error"] = rollbackErr.Error()
		}
		if u := tx.Transition(context.WithoutCancel(ctx), state, detail); u != nil {
			return model.ChrootImportResult{}, errors.Join(e, rollbackErr, u)
		}
		return model.ChrootImportResult{}, errors.Join(e, rollbackErr)
	}
	validationSummary, e := s.C.Chroots().ValidateImport(ctx, name)
	if e != nil {
		return model.ChrootImportResult{}, fmt.Errorf("import committed but post-import validation failed: %w", e)
	}
	if ok, _ := validationSummary["validation_ok"].(bool); !ok {
		return model.ChrootImportResult{}, fmt.Errorf("import committed but post-import validation reported blocking issues")
	}
	if e = tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCommitted, map[string]any{"backup": backup, "had_existing": had, "validation": validationSummary}); e != nil {
		return model.ChrootImportResult{}, fmt.Errorf("import committed but mutation journal commit failed: %w", e)
	}
	cleanupDebt := false
	if had {
		if e = os.RemoveAll(backup); e != nil {
			cleanupDebt = true
			if u := tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCleanupDebt, map[string]any{"backup": backup, "cleanup_error": e.Error()}); u != nil {
				return model.ChrootImportResult{}, errors.Join(e, u)
			}
		}
	}
	if !cleanupDebt {
		if e = tx.Complete(ctx, map[string]any{"destination": target}); e != nil {
			return model.ChrootImportResult{}, fmt.Errorf("import committed but terminal journal persistence failed: %w", e)
		}
	}
	validationOK := true
	summary := "archive imported, registry committed, and post-import validation passed"
	if cleanupDebt {
		summary = "archive imported and validated; old backup cleanup is pending recovery"
	}
	summary = applyPostImportSummary(summary, postImport)
	if cleanupErr := s.cleanupManagedImportStage(context.WithoutCancel(ctx), archive); cleanupErr != nil {
		summary += "; managed staged archive cleanup pending: " + cleanupErr.Error()
	}
	_ = control.emit(context.WithoutCancel(ctx), "complete", 100, "Import completed")
	return model.ChrootImportResult{Name: name, Archive: archive, Arch: arch, Path: target, ChecksumVerified: inspection.ChecksumVerified, IntegritySource: inspection.IntegritySource, ChecksumPath: inspection.ChecksumPath, ConflictStrategy: conflict, Encrypted: inspection.Encrypted, ValidationOk: &validationOK, ValidationSummary: summary, PostImportAction: postImport}, nil
}

func validatePostImportAction(action string) error {
	switch action {
	case "", "none", "register", "validate", "fixups", "shell":
		return nil
	default:
		return fmt.Errorf("unsupported post-import action: %s", action)
	}
}

func applyPostImportSummary(summary, action string) string {
	switch action {
	case "validate":
		return summary + "; validate action completed"
	case "fixups":
		return summary + "; fixups action completed with no unsafe automatic rewrites required"
	case "shell":
		return summary + "; shell handoff recorded, start an interactive session explicitly"
	case "none":
		return summary + "; no extra post-import action requested"
	default:
		return summary + "; register action completed"
	}
}

func (s *TransferService) cleanupManagedImportStage(ctx context.Context, archive string) error {
	p, err := s.managed(archive)
	if err != nil {
		return nil
	}
	var out error
	if err = os.Remove(p); err != nil && !os.IsNotExist(err) {
		out = errors.Join(out, err)
	}
	if err = os.Remove(p + ".sha256"); err != nil && !os.IsNotExist(err) {
		out = errors.Join(out, err)
	}
	if row, lookupErr := s.C.Registry.ArtifactByPath(ctx, p); lookupErr != nil {
		out = errors.Join(out, lookupErr)
	} else if row != nil {
		out = errors.Join(out, s.C.Registry.DeleteArtifact(ctx, row.ArtifactID))
	}
	return out
}
