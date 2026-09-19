package services

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDecompressZstdFileUsesBundledPureGoDecoderAndEmitsProgress(t *testing.T) {
	dir := t.TempDir()
	source := filepath.Join(dir, "archive.tar.zst")
	destination := filepath.Join(dir, "archive.tar")
	compressed := []byte("\x28\xb5\x2f\xfd\x24\x0d\x69\x00\x00\x68\x65\x6c\x6c\x6f\x2c\x20\x77\x6f\x72\x6c\x64\x0a\x4c\x1f\xf9\xf1")
	if err := os.WriteFile(source, compressed, 0o600); err != nil {
		t.Fatal(err)
	}
	var messages []string
	control := TransferControl{Progress: func(v any) error {
		if detail, ok := v.(map[string]any); ok {
			messages = append(messages, strings.TrimSpace(detail["message"].(string)))
		}
		return nil
	}}
	if err := decompressZstdFile(context.Background(), control, source, destination, 12, 20); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(destination)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "hello, world\n" {
		t.Fatalf("decompressed content = %q", got)
	}
	joined := strings.Join(messages, "\n")
	if !strings.Contains(joined, "Decompressing zstd archive") || !strings.Contains(joined, "Archive decompressed") {
		t.Fatalf("progress messages = %q", joined)
	}
}

func TestDecompressZstdFileReturnsUsefulCauseForInvalidArchive(t *testing.T) {
	dir := t.TempDir()
	source := filepath.Join(dir, "broken.tar.zst")
	destination := filepath.Join(dir, "archive.tar")
	if err := os.WriteFile(source, []byte("not-zstd"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := decompressZstdFile(context.Background(), TransferControl{}, source, destination, 12, 20)
	if err == nil {
		t.Fatal("expected decompression failure")
	}
	text := err.Error()
	if !strings.Contains(text, "zstd decompression failed for") || strings.HasSuffix(text, ":") {
		t.Fatalf("error is not actionable: %q", text)
	}
	if _, statErr := os.Stat(destination); !os.IsNotExist(statErr) {
		t.Fatalf("failed decompression left destination behind: %v", statErr)
	}
}
