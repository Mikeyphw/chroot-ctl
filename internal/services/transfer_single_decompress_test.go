package services

import (
	"os"
	"strings"
	"testing"
)

func functionBodyForSourceInvariant(t *testing.T, source, signature string) string {
	t.Helper()
	start := strings.Index(source, signature)
	if start < 0 {
		t.Fatalf("missing function %q", signature)
	}
	rest := source[start+len(signature):]
	next := strings.Index(rest, "\nfunc ")
	if next < 0 {
		return source[start:]
	}
	return source[start : start+len(signature)+next]
}

func TestImportPipelineUsesOnePreparedTarDecompressionInStagedMode(t *testing.T) {
	b, err := os.ReadFile("transfer.go")
	if err != nil {
		t.Fatal(err)
	}
	source := string(b)
	prepare := functionBodyForSourceInvariant(t, source, "func (s *TransferService) prepareImportArchive")
	if got := strings.Count(prepare, "decompressZstdFile("); got != 1 {
		t.Fatalf("prepareImportArchive decompression calls=%d, want exactly 1", got)
	}
	if strings.Contains(source, "materializeTarWithControl") || strings.Contains(source, "func (s *TransferService) materializeTar(") {
		t.Fatal("obsolete second materialization/decompression path is still present")
	}
	importBody := functionBodyForSourceInvariant(t, source, "func (s *TransferService) ImportWithControl")
	if got := strings.Count(importBody, "prepareImportExecution(ctx, archive, password, tmp, control)"); got != 1 {
		t.Fatalf("ImportWithControl preparation calls=%d, want exactly 1", got)
	}
	if strings.Contains(importBody, "decompressZstdFile(") {
		t.Fatal("ImportWithControl performs an extra direct decompression")
	}
	execution := functionBodyForSourceInvariant(t, source, "func (s *TransferService) prepareImportExecution")
	if got := strings.Count(execution, "prepareImportArchive(ctx, archive, password, tmp, control)"); got != 1 {
		t.Fatalf("staged strategy prepared-tar calls=%d, want exactly 1", got)
	}
	if !strings.Contains(execution, "space-efficient streaming import; zstd will be decoded once for preflight and once for extraction") {
		t.Fatal("streaming strategy must explicitly document its two decoder passes")
	}
}
