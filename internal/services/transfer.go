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

	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
)

var artifactTTL = map[string]time.Duration{"staged-import": 24 * time.Hour, "chroot-export": 7 * 24 * time.Hour, "checksum": 7 * 24 * time.Hour, "support-bundle": 3 * 24 * time.Hour, "module-archive": 7 * 24 * time.Hour, "debug-evidence": 3 * 24 * time.Hour, "temporary": 24 * time.Hour}

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
	case strings.Contains(n, "magisk") || strings.Contains(n, "module"):
		return "module-archive"
	case strings.HasSuffix(n, ".tar.zst") || strings.HasSuffix(n, ".tar.zst.enc") || strings.HasSuffix(n, ".tzst") || strings.HasSuffix(n, ".tzst.enc"):
		return "staged-import"
	default:
		return "temporary"
	}
}
func (s *TransferService) managed(path string) (string, error) {
	return contained(ManagedTransferRoot(), path, "managed transfer artifact")
}
func (s *TransferService) RegisterArtifact(ctx context.Context, path, kind, target string, ttl *time.Duration, metadata map[string]any) (*registry.Artifact, error) {
	abs, e := filepath.Abs(path)
	if e != nil {
		return nil, e
	}
	if _, e = contained(ManagedTransferRoot(), abs, "managed transfer artifact"); e != nil {
		return nil, nil
	}
	st, e := os.Stat(abs)
	if e != nil || !st.Mode().IsRegular() {
		return nil, nil
	}
	if kind == "" {
		kind = artifactKind(abs)
	}
	duration := artifactTTL[kind]
	if ttl != nil {
		duration = *ttl
	}
	row, e := s.C.Registry.RegisterArtifact(ctx, registry.ArtifactInput{Path: abs, Kind: kind, Target: target, SizeBytes: st.Size(), TTL: &duration, Metadata: metadata})
	if e != nil {
		return nil, e
	}
	return &row, nil
}
func (s *TransferService) ArtifactRoot() map[string]any {
	root := ManagedTransferRoot()
	return map[string]any{"path": root, "managedRoot": root, "androidDescriptorRoot": "/data/local/tmp/chrootctl-transfer", "exists": exists(root), "writable": writableDir(root), "retentionPolicy": ttlSeconds()}
}
func ttlSeconds() map[string]int64 {
	out := map[string]int64{}
	for k, v := range artifactTTL {
		out[k] = int64(v.Seconds())
	}
	return out
}
func (s *TransferService) TempState(ctx context.Context) (map[string]any, error) {
	root := ManagedTransferRoot()
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
	return map[string]any{"directory": root, "managedRoot": root, "androidDescriptorRoot": "/data/local/tmp/chrootctl-transfer", "retentionPolicy": ttlSeconds(), "count": len(items), "total_bytes": total, "items": items}, nil
}
func (s *TransferService) DeleteTemp(ctx context.Context, id, path string, all bool) (map[string]any, error) {
	removed := 0
	if all {
		rows, _ := s.C.Registry.ListArtifacts(ctx, true, 5000)
		for _, r := range rows {
			if p, e := s.managed(r.Path); e == nil {
				if os.Remove(p) == nil {
					removed++
				}
			}
			_ = s.C.Registry.DeleteArtifact(ctx, r.ArtifactID)
		}
	} else if id != "" {
		r, e := s.C.Registry.GetArtifact(ctx, id)
		if e != nil {
			return nil, e
		}
		p, e := s.managed(r.Path)
		if e != nil {
			return nil, e
		}
		if os.Remove(p) == nil {
			removed++
		}
		_ = s.C.Registry.DeleteArtifact(ctx, id)
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
		if os.Remove(p) == nil {
			removed++
		}
		_ = s.C.Registry.DeleteArtifact(ctx, r.ArtifactID)
	}
	state, e := s.TempState(ctx)
	if e != nil {
		return nil, e
	}
	state["removed"] = removed
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
	for _, m := range rt.Controller.Status(true) {
		if strings.EqualFold(m["mounted"], "yes") {
			return model.ChrootExportResult{}, fmt.Errorf("export requires the chroot to be fully unmounted")
		}
	}
	if archive == "" {
		archive = ManagedArchive(name, "tar.zst")
	}
	archive, _ = filepath.Abs(archive)
	if password != "" && !strings.HasSuffix(archive, ".enc") {
		archive += ".enc"
	}
	if _, e = contained(root, archive, "archive"); e == nil {
		return model.ChrootExportResult{}, fmt.Errorf("archive must be outside chroot source")
	}
	if s.C.DryRun {
		return model.ChrootExportResult{Name: name, Archive: archive, Arch: ptrText(r.Arch), Encrypted: password != ""}, nil
	}
	if e = os.MkdirAll(filepath.Dir(archive), 0755); e != nil {
		return model.ChrootExportResult{}, e
	}
	manifest := map[string]any{"name": name, "distro": r.Distro, "arch": ptrText(r.Arch), "release_name": ptrText(r.ReleaseName), "version": ptrText(r.Version), "phase": r.Phase, "installed": r.Installed, "metadata": r.Metadata, "path_name": filepath.Base(root)}
	manifestPath := filepath.Join(filepath.Dir(root), ".chrootctl-export.json")
	if e = exclusiveJSON(manifestPath, manifest); e != nil {
		return model.ChrootExportResult{}, e
	}
	defer os.Remove(manifestPath)
	baseArchive := archive
	if strings.HasSuffix(baseArchive, ".enc") {
		baseArchive = strings.TrimSuffix(baseArchive, ".enc")
	}
	tmp := filepath.Join(filepath.Dir(archive), "."+filepath.Base(baseArchive)+fmt.Sprintf(".partial-%d", time.Now().UnixNano()))
	if e = control.emit(ctx, "archive", 25, "Creating compressed archive"); e != nil {
		return model.ChrootExportResult{}, e
	}
	runner := transferRunner(rt.Runner, control.Cancelled)
	res, e := runner.Run(ctx, []string{"tar", "--zstd", "-cpf", tmp, "-C", filepath.Dir(root), filepath.Base(root), filepath.Base(manifestPath)}, sys.RunOptions{MaxCaptureBytes: 256 * 1024})
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
	// Publication is the cancellation boundary. After the archive is visible,
	// finish checksum/registration deterministically rather than reporting a
	// cancelled operation that has already committed output. CHR10 owns making
	// archive+sidecar+artifact registration one atomic publication transaction.
	commitCtx := context.WithoutCancel(ctx)
	_ = control.emit(commitCtx, "checksum", 85, "Computing archive checksum")
	sum, e := sha256FileContext(commitCtx, archive)
	if e != nil {
		return model.ChrootExportResult{}, e
	}
	sumPath := archive + ".sha256"
	if e = os.WriteFile(sumPath, []byte(sum+"  "+filepath.Base(archive)+"\n"), 0644); e != nil {
		return model.ChrootExportResult{}, e
	}
	_, _ = s.RegisterArtifact(ctx, archive, "chroot-export", name, nil, map[string]any{"encrypted": password != ""})
	_, _ = s.RegisterArtifact(ctx, sumPath, "checksum", name, nil, map[string]any{"for": archive})
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
func (s *TransferService) Inspect(ctx context.Context, archive, password string) (model.ChrootArchiveInspection, error) {
	return s.InspectWithControl(ctx, archive, password, TransferControl{})
}

func (s *TransferService) InspectWithControl(ctx context.Context, archive, password string, control TransferControl) (model.ChrootArchiveInspection, error) {
	archive, _ = filepath.Abs(archive)
	st, e := os.Stat(archive)
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
	res, e := runner.Run(ctx, []string{"zstd", "-d", "-q", "-f", source, "-o", tarPath}, sys.RunOptions{MaxCaptureBytes: 256 * 1024})
	if e != nil || res.ReturnCode != 0 {
		return model.ChrootArchiveInspection{}, fmt.Errorf("zstd decompression failed: %s", strings.TrimSpace(res.Stderr))
	}
	manifest, size, e := inspectTar(ctx, control, tarPath)
	if e != nil {
		return model.ChrootArchiveInspection{}, e
	}
	pathName := fmt.Sprint(manifest["path_name"])
	sourceName := fmt.Sprint(manifest["name"])
	if sourceName == "" {
		sourceName = pathName
	}
	sumPath := archive + ".sha256"
	var sum *string
	var sumPathPtr *string
	var verified *bool
	if exists(sumPath) {
		text, _ := os.ReadFile(sumPath)
		fields := strings.Fields(string(text))
		if len(fields) > 0 {
			x := fields[0]
			sum = &x
			actual, _ := sha256FileControl(ctx, control, archive)
			ok := actual == x
			verified = &ok
			sumPathPtr = &sumPath
		}
	}
	target, _ := s.C.Registry.Get(ctx, sourceName)
	created := st.ModTime().UTC().Format(time.RFC3339)
	return model.ChrootArchiveInspection{Archive: archive, SourceName: sourceName, SuggestedName: sourceName, PathName: pathName, Distro: fmt.Sprint(manifest["distro"]), Arch: fmt.Sprint(manifest["arch"]), ReleaseName: fmt.Sprint(manifest["release_name"]), Version: fmt.Sprint(manifest["version"]), Phase: fmt.Sprint(manifest["phase"]), Installed: manifest["installed"] == true, Metadata: stringMetadataAny(manifest["metadata"]), SizeBytes: int(st.Size()), ExtractedSizeBytes: int(size), CreatedAt: created, Checksum: sum, ChecksumPath: sumPathPtr, ChecksumVerified: verified, Encrypted: strings.HasSuffix(archive, ".enc"), TargetExists: target != nil, ConflictStrategyOptions: []string{"rename", "overwrite"}}, nil
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
		total += max64(h.Size, 0)
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
	}
	tarPath := filepath.Join(tmp, "archive.tar")
	res, e := runner.Run(ctx, []string{"zstd", "-d", "-q", "-f", source, "-o", tarPath}, sys.RunOptions{MaxCaptureBytes: 256 * 1024})
	if e != nil || res.ReturnCode != 0 {
		return "", fmt.Errorf("zstd decompression failed: %s", strings.TrimSpace(res.Stderr))
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
	if pathName == "" || filepath.Base(pathName) != pathName {
		return fmt.Errorf("invalid archive root name: %q", pathName)
	}
	f, e := os.Open(tarPath)
	if e != nil {
		return e
	}
	defer f.Close()
	tr := tar.NewReader(f)
	prefix := pathName + "/"
	for {
		if err := control.check(ctx); err != nil {
			return err
		}
		h, e := tr.Next()
		if e == io.EOF {
			break
		}
		if e != nil {
			return e
		}
		name := filepath.Clean(h.Name)
		if name == ".chrootctl-export.json" || name == pathName {
			continue
		}
		if !strings.HasPrefix(name, prefix) {
			return fmt.Errorf("unexpected archive member outside root %s: %s", pathName, h.Name)
		}
		rel := strings.TrimPrefix(name, prefix)
		if rel == "" || filepath.IsAbs(rel) || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return fmt.Errorf("unsafe archive member: %s", h.Name)
		}
		target := filepath.Join(destRoot, rel)
		if _, e := contained(destRoot, target, "archive member"); e != nil {
			return e
		}
		if e = safeExtractParent(destRoot, target); e != nil {
			return e
		}
		mode := os.FileMode(h.Mode) & 07777
		switch h.Typeflag {
		case tar.TypeDir:
			if st, e := os.Lstat(target); e == nil {
				if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
					return fmt.Errorf("archive directory collides with unsafe entry: %s", rel)
				}
			} else if os.IsNotExist(e) {
				if e = os.Mkdir(target, mode.Perm()); e != nil {
					return e
				}
			} else {
				return e
			}
		case tar.TypeReg, tar.TypeRegA:
			if st, e := os.Lstat(target); e == nil && st.Mode()&os.ModeSymlink != 0 {
				return fmt.Errorf("archive file collides with symlink: %s", rel)
			}
			out, e := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode.Perm())
			if e != nil {
				return e
			}
			_, copyErr := copyWithControl(ctx, control, out, tr)
			closeErr := out.Close()
			if copyErr != nil {
				return copyErr
			}
			if closeErr != nil {
				return closeErr
			}
		case tar.TypeSymlink:
			if _, e := os.Lstat(target); e == nil {
				return fmt.Errorf("duplicate archive member: %s", rel)
			}
			if e = os.Symlink(h.Linkname, target); e != nil {
				return e
			}
		case tar.TypeLink:
			linkName := filepath.Clean(h.Linkname)
			if !strings.HasPrefix(linkName, prefix) {
				return fmt.Errorf("unsafe hardlink target: %s", h.Linkname)
			}
			linkRel := strings.TrimPrefix(linkName, prefix)
			linkTarget := filepath.Join(destRoot, linkRel)
			if _, e := contained(destRoot, linkTarget, "hardlink target"); e != nil {
				return e
			}
			st, e := os.Lstat(linkTarget)
			if e != nil || !st.Mode().IsRegular() {
				return fmt.Errorf("hardlink target is not a regular extracted file: %s", h.Linkname)
			}
			if e = os.Link(linkTarget, target); e != nil {
				return e
			}
		default: /* device/fifo/socket entries are recreated by runtime preparation */
		}
	}
	return nil
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
	if s.C.DryRun {
		if name == "" {
			base := filepath.Base(archive)
			for _, suffix := range []string{".tar.zst.enc", ".tar.zst", ".tar.gz", ".tgz", ".enc"} {
				base = strings.TrimSuffix(base, suffix)
			}
			name = base
		}
		safe, e := validation.ChrootName(name)
		if e != nil {
			return model.ChrootImportResult{}, e
		}
		name = safe
		ok := true
		return model.ChrootImportResult{Name: name, Archive: archive, Path: filepath.Join(s.C.BaseConfig.ChrootRoot, name), ConflictStrategy: conflict, Encrypted: strings.HasSuffix(archive, ".enc"), ValidationOk: &ok, ValidationSummary: "dry-run: archive exists; extraction and publication were not performed", PostImportAction: postImport}, nil
	}
	if e := control.emit(ctx, "inspect", 5, "Inspecting import archive"); e != nil {
		return model.ChrootImportResult{}, e
	}
	inspection, e := s.InspectWithControl(ctx, archive, password, control)
	if e != nil {
		return model.ChrootImportResult{}, e
	}
	if inspection.ChecksumVerified != nil && !*inspection.ChecksumVerified {
		return model.ChrootImportResult{}, fmt.Errorf("archive checksum verification failed")
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
		for _, m := range rt.Controller.Status(true) {
			if strings.EqualFold(m["mounted"], "yes") {
				return model.ChrootImportResult{}, fmt.Errorf("overwrite import requires the existing chroot to be fully unmounted")
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
	if e = tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCommitted, map[string]any{"backup": backup, "had_existing": had}); e != nil {
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
	summary := "archive imported and registry record committed"
	if cleanupDebt {
		summary = "archive imported; old backup cleanup is pending recovery"
	}
	if postImport == "" {
		postImport = "none"
	}
	_ = control.emit(context.WithoutCancel(ctx), "complete", 100, "Import completed")
	return model.ChrootImportResult{Name: name, Archive: archive, Arch: arch, Path: target, ChecksumVerified: inspection.ChecksumVerified, ChecksumPath: inspection.ChecksumPath, ConflictStrategy: conflict, Encrypted: inspection.Encrypted, ValidationOk: &validationOK, ValidationSummary: summary, PostImportAction: postImport}, nil
}
