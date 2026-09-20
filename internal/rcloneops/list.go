package rcloneops

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type Entry struct {
	Name    string    `json:"Name"`
	Path    string    `json:"Path"`
	Size    int64     `json:"Size"`
	ModTime time.Time `json:"ModTime"`
	IsDir   bool      `json:"IsDir"`
}

func (r Runtime) List(ctx context.Context, location string) ([]Entry, error) {
	if !IsLocation(location) {
		return nil, fmt.Errorf("rclone list requires rclone://remote/path")
	}
	if err := r.requireConfigForRemote(location); err != nil {
		return nil, err
	}
	resolved, err := commandLocation(location)
	if err != nil {
		return nil, err
	}
	args := append([]string{"lsjson", resolved, "--max-depth", "1", "--no-mimetype"}, r.baseArgs()...)
	out, err := r.commandOutput(ctx, args)
	if err != nil {
		return nil, err
	}
	var entries []Entry
	if err := json.Unmarshal(out, &entries); err != nil {
		return nil, fmt.Errorf("decode rclone lsjson output: %w", err)
	}
	for i := range entries {
		if strings.TrimSpace(entries[i].Name) == "" || strings.ContainsRune(entries[i].Path, '\x00') {
			return nil, fmt.Errorf("rclone returned invalid remote entry")
		}
		if entries[i].Size < 0 {
			entries[i].Size = 0
		}
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].IsDir != entries[j].IsDir {
			return entries[i].IsDir
		}
		return strings.ToLower(entries[i].Name) < strings.ToLower(entries[j].Name)
	})
	return entries, nil
}

func (r Runtime) Stat(ctx context.Context, value string) (Entry, error) {
	if !IsLocation(value) {
		absolute, err := filepath.Abs(value)
		if err != nil {
			return Entry{}, err
		}
		info, err := os.Stat(absolute)
		if err != nil {
			return Entry{}, err
		}
		return Entry{Name: info.Name(), Path: absolute, Size: max64(info.Size(), 0), ModTime: info.ModTime(), IsDir: info.IsDir()}, nil
	}
	if err := r.requireConfigForRemote(value); err != nil {
		return Entry{}, err
	}
	resolved, err := commandLocation(value)
	if err != nil {
		return Entry{}, err
	}
	args := append([]string{"lsjson", resolved, "--stat", "--no-mimetype"}, r.baseArgs()...)
	out, err := r.commandOutput(ctx, args)
	if err != nil {
		return Entry{}, err
	}
	var entry Entry
	if err := json.Unmarshal(out, &entry); err != nil {
		return Entry{}, fmt.Errorf("decode rclone stat output: %w", err)
	}
	if entry.Name == "" {
		entry.Name = BaseName(value)
	}
	if entry.Size < 0 {
		entry.Size = 0
	}
	return entry, nil
}

func (r Runtime) commandOutput(ctx context.Context, args []string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, r.Executable, args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		d := r.sanitizeDiagnostic(stderr.String())
		if d != "" {
			return nil, fmt.Errorf("%w: %s", commandError("rclone", err), d)
		}
		return nil, commandError("rclone", err)
	}
	return out, nil
}

// Exists checks one remote object without downloading its contents. Missing
// objects return (false, nil); all other rclone/provider failures remain errors.
func (r Runtime) Exists(ctx context.Context, value string) (bool, error) {
	if !IsLocation(value) {
		_, err := os.Stat(value)
		if os.IsNotExist(err) {
			return false, nil
		}
		return err == nil, err
	}
	_, err := r.Stat(ctx, value)
	if err == nil {
		return true, nil
	}
	if isNotFoundError(err) {
		return false, nil
	}
	return false, err
}

func isNotFoundError(err error) bool {
	if err == nil {
		return false
	}
	text := strings.ToLower(err.Error())
	for _, marker := range []string{
		"object not found",
		"directory not found",
		"file not found",
		"not found",
		"doesn't exist",
		"does not exist",
	} {
		if strings.Contains(text, marker) {
			return true
		}
	}
	return false
}
