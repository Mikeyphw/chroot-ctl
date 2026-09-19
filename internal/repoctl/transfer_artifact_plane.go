package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateTransferArtifactPlane is the executable CHR10 source seal. It keeps
// transfer/import/archive paths on the managed artifact plane and prevents
// regressions that would reintroduce unchecked imports, silently orphaned
// artifacts, or Android staged archives without integrity evidence.
func ValidateTransferArtifactPlane(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR10 read %s: %w", rel, err)
		}
		return string(b), nil
	}
	mustContain := func(rel string, tokens ...string) error {
		text, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if !strings.Contains(text, token) {
				return fmt.Errorf("CHR10 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	if err := mustContain("internal/services/transfer.go",
		"func EnsureManagedTransferRoot()",
		"maxManagedArtifactBytes",
		"maxArchiveExpandedBytes",
		"func requireArchiveChecksum(",
		"os.IsNotExist(err)",
		`return "computed_on_import"`,
		"archive checksum verification failed",
		"func validateImportManifest(",
		"func (s *TransferService) ReconcileArtifacts(",
		"RegisterArtifact(commitCtx, archive, \"chroot-export\"",
		"s.C.Chroots().ValidateImport(ctx, name)",
		"cleanupManagedImportStage",
	); err != nil {
		return err
	}
	transferText, err := read("internal/services/transfer.go")
	if err != nil {
		return err
	}
	if strings.Count(transferText, `control.emit(commitCtx, "checksum", 85, "Computing archive checksum")`) != 1 {
		return fmt.Errorf("CHR10 transfer export must emit checksum progress exactly once")
	}
	if err := mustContain("internal/services/chroots.go",
		"func (s *ChrootService) ValidateImport(",
		"registry.path",
		"registry.import_marker",
		"ManagedArchive(name, \"tar.zst\")",
		"archive_outside_managed_root",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/support.go",
		"ManagedArchive(fmt.Sprintf(\"chrootctl-support-%d\"",
		"os.Rename(tmpName, archive)",
		"RegisterArtifact(ctx, archive, \"support-bundle\"",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/module_build.go",
		"ManagedArchive(\"chrootctl-magisk\", \"zip\")",
		"contained(managedRoot, abs, \"module artifact\")",
		"RegisterArtifact(ctx, abs, \"module-archive\"",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/backend.go",
		"case \"artifacts.list\":",
		"return s.Transfer().TempState(ctx)",
		"return b.Services.Transfer().DeleteTemp(ctx, id, path, all)",
		"case \"support.preview\":",
		"services.ManagedArchive(\"chrootctl-support\", \"tar.gz\")",
		"containedBridgePath(root, abs, \"support bundle artifact\")",
		"services.ManagedArchive(\"smoke-result-\"+kind, \"json\")",
		"containedBridgePath(root, abs, \"smoke artifact\")",
		"if b.Services.DryRun {",
		`"dry_run": true, "archive": archive, "artifact": nil`,
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt",
		"publishChecksumSidecar(target, checksum)",
		"MessageDigest.getInstance(\"SHA-256\")",
		"checksum_path",
		"readTransferState(requestId) != null",
		"create a new request id for each transfer",
		"partial.delete()",
	); err != nil {
		return err
	}
	if err := mustContain("migration/contracts/v1/cli.json",
		"\"command\": \"artifacts cleanup\"",
		"An adjacent .sha256 sidecar is verified when present; otherwise SHA-256 is computed on import.",
		"--allow-legacy-metadata",
		"managed transfer artifact root",
	); err != nil {
		return err
	}
	raw, err := os.ReadFile(filepath.Join(root, "docs", "audit", "roadmap-coverage.json"))
	if err != nil {
		return fmt.Errorf("CHR10 read roadmap coverage: %w", err)
	}
	var coverage auditCoverage
	if err := json.Unmarshal(raw, &coverage); err != nil {
		return fmt.Errorf("CHR10 parse roadmap coverage: %w", err)
	}
	chr10 := map[string]bool{"D18": true, "D19": true, "D39": true, "D41": true, "U054": true, "U055": true, "U056": true, "U057": true, "U058": true, "U059": true, "U060": true, "U157": true, "U158": true, "U159": true, "U160": true, "U161": true, "U162": true, "U163": true, "U164": true, "U165": true, "U166": true, "U167": true, "U168": true, "U169": true}
	seen := map[string]bool{}
	sources := 0
	for _, finding := range coverage.CanonicalFindings {
		if !chr10[finding.ID] {
			continue
		}
		if finding.OwnerOverlay != "CHR10" || finding.Status == "planned" {
			return fmt.Errorf("CHR10 finding %s is not marked implemented", finding.ID)
		}
		seen[finding.ID] = true
		sources += len(finding.SourceFindings)
	}
	if len(seen) != len(chr10) {
		return fmt.Errorf("CHR10 implemented coverage=%d, want %d", len(seen), len(chr10))
	}
	if sources != 49 {
		return fmt.Errorf("CHR10 source-manifestation coverage=%d, want 49", sources)
	}
	return nil
}
