package services

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"chrootctl/internal/model"
	"chrootctl/internal/rcloneops"
)

type byteCounter struct {
	mu sync.Mutex
	n  int64
}

func (c *byteCounter) Write(p []byte) (int, error) {
	c.mu.Lock()
	c.n += int64(len(p))
	c.mu.Unlock()
	return len(p), nil
}
func (c *byteCounter) Value() int64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.n
}

func commandDiagnostic(stderr *bytes.Buffer, action string, err error) error {
	text := strings.TrimSpace(stderr.String())
	if len(text) > 4096 {
		text = text[len(text)-4096:]
	}
	if text == "" {
		return fmt.Errorf("%s failed: %w", action, err)
	}
	return fmt.Errorf("%s failed: %s", action, text)
}

// streamExportArchive writes the exact final archive bytes to output without
// materializing a compressed archive on local storage. Passwords are passed to
// openssl via a process-local environment variable rather than argv/stdin so
// tar's stream remains available on stdin.
func streamExportArchive(ctx context.Context, root, manifestDir, manifestPath, password string, output io.Writer) error {
	tarPath, err := exec.LookPath("tar")
	if err != nil {
		return fmt.Errorf("tar is required for chroot export: %w", err)
	}
	tarArgs := []string{"--format=pax", "--numeric-owner", "--acls", "--xattrs", "--xattrs-include=*", "--sparse", "--one-file-system", "--zstd", "-cpf", "-", "-C", filepath.Dir(root), filepath.Base(root), "-C", manifestDir, filepath.Base(manifestPath)}
	tarCmd := exec.CommandContext(ctx, tarPath, tarArgs...)
	var tarErr bytes.Buffer
	tarCmd.Stderr = &tarErr
	if password == "" {
		tarCmd.Stdout = output
		if err := tarCmd.Run(); err != nil {
			return commandDiagnostic(&tarErr, "tar/zstd export stream", err)
		}
		return nil
	}

	opensslPath, err := exec.LookPath("openssl")
	if err != nil {
		return fmt.Errorf("openssl is required for encrypted chroot export: %w", err)
	}
	tarOut, err := tarCmd.StdoutPipe()
	if err != nil {
		return err
	}
	opensslCmd := exec.CommandContext(ctx, opensslPath, "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-pass", "env:CHROOTCTL_EXPORT_PASSWORD")
	opensslCmd.Env = append(os.Environ(), "CHROOTCTL_EXPORT_PASSWORD="+password)
	opensslCmd.Stdin = tarOut
	opensslCmd.Stdout = output
	var opensslErr bytes.Buffer
	opensslCmd.Stderr = &opensslErr
	if err := opensslCmd.Start(); err != nil {
		return fmt.Errorf("start openssl export encryption: %w", err)
	}
	if err := tarCmd.Start(); err != nil {
		_ = opensslCmd.Process.Kill()
		_ = opensslCmd.Wait()
		return fmt.Errorf("start tar/zstd export stream: %w", err)
	}
	tarWait := tarCmd.Wait()
	opensslWait := opensslCmd.Wait()
	if tarWait != nil {
		return commandDiagnostic(&tarErr, "tar/zstd export stream", tarWait)
	}
	if opensslWait != nil {
		return commandDiagnostic(&opensslErr, "archive encryption stream", opensslWait)
	}
	return nil
}

func normalizeRemoteExportDestination(remote, password string) (string, string, error) {
	if password != "" && !strings.HasSuffix(remote, ".enc") {
		remote += ".enc"
	}
	canonical, err := rcloneops.CanonicalURI(remote)
	if err != nil {
		return "", "", err
	}
	return canonical, canonical + ".sha256", nil
}

func (s *TransferService) exportRemoteWithControl(ctx context.Context, name, remote, password string, control TransferControl) (model.ChrootExportResult, error) {
	runtime, err := s.C.RcloneRuntime()
	if err != nil {
		return model.ChrootExportResult{}, err
	}
	remote, sidecarRemote, err := normalizeRemoteExportDestination(remote, password)
	if err != nil {
		return model.ChrootExportResult{}, err
	}
	if err := runtime.ValidateLocation(remote); err != nil {
		return model.ChrootExportResult{}, err
	}
	for _, destination := range []string{remote, sidecarRemote} {
		exists, existsErr := runtime.Exists(ctx, destination)
		if existsErr != nil {
			return model.ChrootExportResult{}, fmt.Errorf("check remote export destination %s: %w", destination, existsErr)
		}
		if exists {
			return model.ChrootExportResult{}, fmt.Errorf("remote export destination already exists: %s", destination)
		}
	}
	if err = control.emit(ctx, "remote-export", 3, "Preparing streamed remote export"); err != nil {
		return model.ChrootExportResult{}, err
	}
	r, err := s.C.Registry.Get(ctx, name)
	if err != nil || r == nil {
		if err == nil {
			err = fmt.Errorf("no registry record for chroot: %s", name)
		}
		return model.ChrootExportResult{}, err
	}
	rt, err := s.C.RuntimeFor(name, "")
	if err != nil {
		return model.ChrootExportResult{}, err
	}
	root, err := contained(rt.Config.ChrootRoot, r.Path, "registered chroot path")
	if err != nil {
		return model.ChrootExportResult{}, err
	}
	manifest := map[string]any{
		"name": name, "distro": r.Distro, "arch": ptrText(r.Arch), "release_name": ptrText(r.ReleaseName),
		"version": ptrText(r.Version), "phase": r.Phase, "installed": r.Installed, "metadata": r.Metadata,
		"path_name": filepath.Base(root), "rootfs_metadata_contract": "chrootctl-rootfs-v1",
		"rootfs_metadata_features": []string{"uid_gid", "mode_special_bits", "atime_mtime", "xattrs_acl_capabilities", "hardlinks", "symlinks", "fifo_device_nodes", "sparse_zero_ranges"},
	}
	manifestDir, err := os.MkdirTemp("", ".chrootctl-remote-export-manifest-")
	if err != nil {
		return model.ChrootExportResult{}, err
	}
	defer os.RemoveAll(manifestDir)
	manifestPath := filepath.Join(manifestDir, exportManifestMember)
	if err = exclusiveJSON(manifestPath, manifest); err != nil {
		return model.ChrootExportResult{}, err
	}

	suffix := fmt.Sprintf(".partial-%d", time.Now().UnixNano())
	remoteTemp := remote + suffix
	sidecarTemp := sidecarRemote + suffix
	archivePublished := false
	sidecarPublished := false
	publicationVerified := false
	defer func() {
		_ = runtime.Delete(context.WithoutCancel(ctx), remoteTemp)
		_ = runtime.Delete(context.WithoutCancel(ctx), sidecarTemp)
		if !publicationVerified {
			if archivePublished {
				_ = runtime.Delete(context.WithoutCancel(ctx), remote)
			}
			if sidecarPublished {
				_ = runtime.Delete(context.WithoutCancel(ctx), sidecarRemote)
			}
		}
	}()

	streamCtx, streamCancel := context.WithCancel(ctx)
	defer streamCancel()
	pr, pw := io.Pipe()
	hasher := sha256.New()
	counter := &byteCounter{}
	producerDone := make(chan error, 1)
	go func() {
		writer := io.MultiWriter(pw, hasher, counter)
		produceErr := streamExportArchive(streamCtx, root, manifestDir, manifestPath, password, writer)
		_ = pw.CloseWithError(produceErr)
		producerDone <- produceErr
	}()

	if err = control.emit(ctx, "remote-upload", 15, "Streaming compressed archive directly to remote"); err != nil {
		streamCancel()
		_ = pr.Close()
		<-producerDone
		return model.ChrootExportResult{}, err
	}
	uploadErr := runtime.Rcat(ctx, remoteTemp, pr, rcloneops.StreamOptions{Cancelled: control.Cancelled, Progress: func(progress rcloneops.Progress) {
		if progress.BytesDone <= 0 {
			progress.BytesDone = counter.Value()
		}
		detail := rcloneProgressDetail(progress, remote)
		detail["remote"] = remote
		percent := 55
		if progress.BytesTotal > 0 {
			percent = rcloneProgressPercent(progress, 15, 84)
		}
		_ = control.emitDetail(ctx, "remote-upload", percent, "Streaming compressed archive to remote", detail)
	}})
	streamCancel()
	producerErr := <-producerDone
	if uploadErr != nil {
		return model.ChrootExportResult{}, uploadErr
	}
	if producerErr != nil {
		return model.ChrootExportResult{}, producerErr
	}
	archiveBytes := counter.Value()
	if archiveBytes <= 0 {
		return model.ChrootExportResult{}, fmt.Errorf("remote export produced an empty archive stream")
	}
	sum := hex.EncodeToString(hasher.Sum(nil))
	if err = control.emit(ctx, "remote-verify", 85, "Verifying uploaded remote archive before publication"); err != nil {
		return model.ChrootExportResult{}, err
	}
	verifyHasher := sha256.New()
	var verifiedBytes int64
	if err = runtime.StreamRead(ctx, remoteTemp, rcloneops.StreamOptions{Cancelled: control.Cancelled, Progress: func(progress rcloneops.Progress) {
		emitRcloneProgress(ctx, control, "remote-verify", 85, 90, "Verifying uploaded remote archive", remoteTemp, progress)
	}}, func(reader io.Reader) error {
		written, copyErr := copyWithControl(ctx, control, verifyHasher, reader)
		verifiedBytes = written
		return copyErr
	}); err != nil {
		return model.ChrootExportResult{}, fmt.Errorf("verify uploaded remote archive: %w", err)
	}
	if verifiedBytes != archiveBytes || hex.EncodeToString(verifyHasher.Sum(nil)) != sum {
		return model.ChrootExportResult{}, fmt.Errorf("remote export verification failed before publication: bytes=%d want=%d", verifiedBytes, archiveBytes)
	}
	sidecarBody := sum + "  " + rcloneops.BaseName(remote) + "\n"
	if err = control.emit(ctx, "remote-checksum", 92, "Publishing remote checksum sidecar"); err != nil {
		return model.ChrootExportResult{}, err
	}
	if err = runtime.Rcat(ctx, sidecarTemp, strings.NewReader(sidecarBody), rcloneops.StreamOptions{Cancelled: control.Cancelled}); err != nil {
		return model.ChrootExportResult{}, err
	}
	if err = runtime.Move(ctx, sidecarTemp, sidecarRemote); err != nil {
		return model.ChrootExportResult{}, err
	}
	sidecarPublished = true
	if err = control.emit(ctx, "remote-commit", 97, "Publishing remote archive"); err != nil {
		return model.ChrootExportResult{}, err
	}
	if err = runtime.Move(ctx, remoteTemp, remote); err != nil {
		return model.ChrootExportResult{}, err
	}
	archivePublished = true

	final, err := runtime.Stat(ctx, remote)
	if err != nil {
		return model.ChrootExportResult{}, err
	}
	if final.IsDir || final.Size != archiveBytes {
		return model.ChrootExportResult{}, fmt.Errorf("remote export verification failed: size=%d want=%d", final.Size, archiveBytes)
	}
	remoteSidecar, found, err := runtime.ReadSmall(ctx, sidecarRemote, 4096)
	if err != nil || !found || string(remoteSidecar) != sidecarBody {
		if err != nil {
			return model.ChrootExportResult{}, fmt.Errorf("verify remote checksum sidecar: %w", err)
		}
		return model.ChrootExportResult{}, fmt.Errorf("remote checksum sidecar verification failed")
	}
	publicationVerified = true
	if err = control.emit(context.WithoutCancel(ctx), "complete", 100, "Remote export completed"); err != nil {
		return model.ChrootExportResult{}, err
	}
	arch := ptrText(r.Arch)
	return model.ChrootExportResult{Name: name, Archive: remote, Arch: arch, Checksum: &sum, ChecksumPath: &sidecarRemote, Encrypted: password != ""}, nil
}
