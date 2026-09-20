package rcloneops

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type Progress struct {
	BytesDone          int64
	BytesTotal         int64
	FilesDone          int64
	FilesTotal         int64
	RateBytesPerSecond int64
	ETASeconds         int64
	CurrentObject      string
}
type StreamOptions struct {
	Cancelled func() bool
	Progress  func(Progress)
}
type transferDocument struct {
	Name       string          `json:"name"`
	Bytes      int64           `json:"bytes"`
	Size       int64           `json:"size"`
	Percentage float64         `json:"percentage"`
	Speed      float64         `json:"speed"`
	ETA        json.RawMessage `json:"eta"`
}
type statsDocument struct {
	Bytes          int64              `json:"bytes"`
	Transfers      int64              `json:"transfers"`
	TotalBytes     int64              `json:"totalBytes"`
	TotalTransfers int64              `json:"totalTransfers"`
	Speed          float64            `json:"speed"`
	ETA            json.RawMessage    `json:"eta"`
	Transferring   []transferDocument `json:"transferring"`
}
type logDocument struct {
	Stats *statsDocument `json:"stats"`
}

func etaSeconds(raw json.RawMessage) int64 {
	if len(raw) == 0 || string(raw) == "null" {
		return -1
	}
	var numeric float64
	if json.Unmarshal(raw, &numeric) == nil && numeric >= 0 {
		return int64(numeric + 0.5)
	}
	var text string
	if json.Unmarshal(raw, &text) == nil {
		text = strings.TrimSpace(text)
		if text == "" || text == "-" {
			return -1
		}
		if duration, err := time.ParseDuration(text); err == nil && duration >= 0 {
			return int64(duration.Round(time.Second) / time.Second)
		}
	}
	return -1
}

func progressFromStats(stats statsDocument, fallbackObject string) Progress {
	rate := int64(stats.Speed + 0.5)
	eta := etaSeconds(stats.ETA)
	current := ""
	for _, item := range stats.Transferring {
		if strings.TrimSpace(item.Name) == "" {
			continue
		}
		current = item.Name
		if rate <= 0 && item.Speed > 0 {
			rate = int64(item.Speed + 0.5)
		}
		if eta < 0 {
			eta = etaSeconds(item.ETA)
		}
		break
	}
	if current == "" {
		current = fallbackObject
	}
	return Progress{
		BytesDone: stats.Bytes, BytesTotal: stats.TotalBytes,
		FilesDone: stats.Transfers, FilesTotal: stats.TotalTransfers,
		RateBytesPerSecond: rate, ETASeconds: eta, CurrentObject: current,
	}
}

func (r Runtime) ReadSmall(ctx context.Context, location string, max int64) ([]byte, bool, error) {
	if max <= 0 {
		max = 1 << 20
	}
	var buf bytes.Buffer
	err := r.StreamRead(ctx, location, StreamOptions{}, func(reader io.Reader) error {
		n, err := io.CopyN(&buf, reader, max+1)
		if err != nil && err != io.EOF {
			return err
		}
		if n > max {
			return fmt.Errorf("remote object exceeds %d bytes", max)
		}
		return nil
	})
	if err != nil {
		if isNotFoundError(err) {
			return nil, false, nil
		}
		return nil, false, err
	}
	return buf.Bytes(), true, nil
}

func (r Runtime) StreamRead(ctx context.Context, location string, options StreamOptions, consume func(io.Reader) error) error {
	if !IsLocation(location) {
		return fmt.Errorf("rclone stream read requires rclone:// remote location")
	}
	if err := r.requireConfigForRemote(location); err != nil {
		return err
	}
	resolved, err := commandLocation(location)
	if err != nil {
		return err
	}
	args := []string{"cat", resolved, "--use-json-log", "--stats", "500ms", "--stats-log-level", "NOTICE", "--log-level", "NOTICE"}
	args = append(args, r.baseArgs()...)
	cmdCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	cmd := exec.CommandContext(cmdCtx, r.Executable, args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	if err = cmd.Start(); err != nil {
		return commandError("start rclone", err)
	}
	diagnostics := make(chan []string, 1)
	go func() {
		lines := []string{}
		scan := bufio.NewScanner(stderr)
		scan.Buffer(make([]byte, 64*1024), 1024*1024)
		for scan.Scan() {
			line := scan.Text()
			var doc logDocument
			if json.Unmarshal([]byte(line), &doc) == nil && doc.Stats != nil {
				if options.Progress != nil {
					options.Progress(progressFromStats(*doc.Stats, BaseName(location)))
				}
				continue
			}
			if d := r.sanitizeDiagnostic(line); d != "" {
				lines = append(lines, d)
				if len(lines) > 8 {
					lines = lines[len(lines)-8:]
				}
			}
		}
		diagnostics <- lines
	}()
	cancelDone := make(chan struct{})
	go func() {
		defer close(cancelDone)
		t := time.NewTicker(150 * time.Millisecond)
		defer t.Stop()
		for {
			select {
			case <-cmdCtx.Done():
				return
			case <-t.C:
				if options.Cancelled != nil && options.Cancelled() {
					cancel()
					return
				}
			}
		}
	}()
	consumeErr := consume(stdout)
	if consumeErr != nil {
		cancel()
	}
	waitErr := cmd.Wait()
	lines := <-diagnostics
	cancel()
	<-cancelDone
	if consumeErr != nil {
		return consumeErr
	}
	if errors.Is(cmdCtx.Err(), context.Canceled) && options.Cancelled != nil && options.Cancelled() {
		return context.Canceled
	}
	if waitErr != nil {
		if len(lines) > 0 {
			return fmt.Errorf("rclone failed: %s", strings.Join(lines, " | "))
		}
		return commandError("rclone", waitErr)
	}
	return nil
}

func (r Runtime) Rcat(ctx context.Context, location string, reader io.Reader, options StreamOptions) error {
	if !IsLocation(location) {
		return fmt.Errorf("rclone rcat requires rclone:// remote location")
	}
	if err := r.requireConfigForRemote(location); err != nil {
		return err
	}
	resolved, err := commandLocation(location)
	if err != nil {
		return err
	}
	args := []string{"rcat", resolved, "--use-json-log", "--stats", "500ms", "--stats-log-level", "NOTICE", "--log-level", "NOTICE", "--retries", "3", "--low-level-retries", "5"}
	args = append(args, r.baseArgs()...)
	return r.runInputCommand(ctx, args, reader, options, BaseName(location))
}

func (r Runtime) Move(ctx context.Context, source, destination string) error {
	if err := r.requireConfigForRemote(source, destination); err != nil {
		return err
	}
	src, err := commandLocation(source)
	if err != nil {
		return err
	}
	dst, err := commandLocation(destination)
	if err != nil {
		return err
	}
	args := []string{"moveto", src, dst, "--immutable", "--retries", "3", "--low-level-retries", "5"}
	args = append(args, r.baseArgs()...)
	_, err = r.commandOutput(ctx, args)
	return err
}
func (r Runtime) Delete(ctx context.Context, location string) error {
	if err := r.requireConfigForRemote(location); err != nil {
		return err
	}
	v, err := commandLocation(location)
	if err != nil {
		return err
	}
	args := []string{"deletefile", v}
	args = append(args, r.baseArgs()...)
	_, err = r.commandOutput(ctx, args)
	return err
}

func (r Runtime) runInputCommand(ctx context.Context, args []string, reader io.Reader, options StreamOptions, fallbackObject string) error {
	cmdCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	cmd := exec.CommandContext(cmdCtx, r.Executable, args...)
	cmd.Stdin = reader
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err = cmd.Start(); err != nil {
		return commandError("start rclone", err)
	}
	var wg sync.WaitGroup
	diagnostics := []string{}
	var mu sync.Mutex
	wg.Add(1)
	go func() {
		defer wg.Done()
		scan := bufio.NewScanner(stderr)
		scan.Buffer(make([]byte, 64*1024), 1024*1024)
		for scan.Scan() {
			line := scan.Text()
			var doc logDocument
			if json.Unmarshal([]byte(line), &doc) == nil && doc.Stats != nil {
				if options.Progress != nil {
					options.Progress(progressFromStats(*doc.Stats, fallbackObject))
				}
				continue
			}
			if d := r.sanitizeDiagnostic(line); d != "" {
				mu.Lock()
				diagnostics = append(diagnostics, d)
				if len(diagnostics) > 8 {
					diagnostics = diagnostics[len(diagnostics)-8:]
				}
				mu.Unlock()
			}
		}
	}()
	cancelDone := make(chan struct{})
	go func() {
		defer close(cancelDone)
		t := time.NewTicker(150 * time.Millisecond)
		defer t.Stop()
		for {
			select {
			case <-cmdCtx.Done():
				return
			case <-t.C:
				if options.Cancelled != nil && options.Cancelled() {
					cancel()
					return
				}
			}
		}
	}()
	waitErr := cmd.Wait()
	wg.Wait()
	cancel()
	<-cancelDone
	if errors.Is(cmdCtx.Err(), context.Canceled) && options.Cancelled != nil && options.Cancelled() {
		return context.Canceled
	}
	if waitErr != nil {
		mu.Lock()
		d := strings.Join(diagnostics, " | ")
		mu.Unlock()
		if d != "" {
			return fmt.Errorf("rclone failed: %s", d)
		}
		return commandError("rclone", waitErr)
	}
	return nil
}

func ImportConfig(staged string) (string, error) {
	src, err := filepath.Abs(staged)
	if err != nil {
		return "", err
	}
	st, err := os.Lstat(src)
	if err != nil {
		return "", err
	}
	if !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 || st.Size() <= 0 || st.Size() > 4*1024*1024 {
		return "", fmt.Errorf("invalid rclone config source")
	}
	raw, err := os.ReadFile(src)
	if err != nil {
		return "", err
	}
	if strings.HasPrefix(strings.TrimSpace(string(raw)), "RCLONE_ENCRYPT_V0:") {
		return "", fmt.Errorf("encrypted rclone.conf is not supported; import a decrypted config so chrootctl can validate remote names without persisting a config password")
	}
	names := remoteNamesInConfig(string(raw))
	if len(names) == 0 {
		return "", fmt.Errorf("rclone config contains no valid remote sections")
	}
	destination := strings.TrimSpace(os.Getenv("CHROOTCTL_RCLONE_CONFIG"))
	if destination == "" {
		destination = DefaultConfigPath
	}
	destination, err = filepath.Abs(destination)
	if err != nil {
		return "", err
	}
	dir := filepath.Dir(destination)
	if err = os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	if st, statErr := os.Lstat(dir); statErr != nil || st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
		return "", fmt.Errorf("unsafe rclone config directory: %s", dir)
	}
	if err = os.Chmod(dir, 0o700); err != nil {
		return "", err
	}
	if os.Geteuid() == 0 {
		if err = os.Chown(dir, 0, 0); err != nil {
			return "", fmt.Errorf("set rclone config directory ownership: %w", err)
		}
	}
	tmp, err := os.CreateTemp(dir, ".rclone.conf.tmp-")
	if err != nil {
		return "", err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if _, err = tmp.Write(raw); err != nil {
		tmp.Close()
		return "", err
	}
	if err = tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return "", err
	}
	if err = tmp.Sync(); err != nil {
		tmp.Close()
		return "", err
	}
	if err = tmp.Close(); err != nil {
		return "", err
	}
	if err = os.Rename(tmpName, destination); err != nil {
		return "", err
	}
	if err = os.Chmod(destination, 0o600); err != nil {
		return "", err
	}
	if os.Geteuid() == 0 {
		if err = os.Chown(destination, 0, 0); err != nil {
			return "", fmt.Errorf("set rclone config ownership: %w", err)
		}
	}
	return destination, nil
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}
