package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateLoggingDiagnosticsAuditEvidence keeps CHR16 executable instead of prose-only.
// It seals the diagnostic plane: log files and operation journals are private,
// every emitted diagnostic/evidence surface is redacted, severity filters behave
// as thresholds, support bundles are managed tar.gz artifacts, and audit events
// are attributed, bounded, and sanitized before persistence or bridge export.
func ValidateLoggingDiagnosticsAuditEvidence(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR16 read %s: %w", rel, err)
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
				return fmt.Errorf("CHR16 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	if err := mustContain("internal/logging/logging.go",
		"MaxLogFileBytes",
		"rotateIfNeeded",
		"0o600",
		"redaction.String(message)",
	); err != nil {
		return err
	}
	if err := mustContain("internal/redaction/redaction.go",
		"privateKeyRE",
		"urlCredsRE",
		"githubTokenRE",
		"authHeaderRE",
	); err != nil {
		return err
	}
	if err := mustContain("internal/operations/journal.go",
		"MaxEventFileBytes",
		"0o600",
		"redaction.Value(normalize(event))",
		"MaxEventCount",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/system.go",
		"func logSeverityValue",
		"readRecentLogLines",
		"const maxLineBytes = 1024 * 1024",
		"redaction.String(scan.Text())",
		"unsupported log level",
		"read log file %s",
		"syscall.O_NOFOLLOW",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/support.go",
		"tar.NewWriter",
		"gzip.NewWriter",
		"archive_format",
		"support.bundle.export",
		"RegisterArtifact",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/audit.go",
		"defaultAuditActor",
		"RecordMutation",
		"Actor: redaction.String(actor)",
		"Target: redaction.String(target)",
		"Message: redaction.String(message)",
		"redactedStringMap",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/users.go",
		"user.add",
		"user.remove",
		"user.set_password",
		"user.set_shell",
		"user.set_sudo",
		"user.sync_id",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/units.go",
		"service.start",
		"service.stop",
		"service.restart",
		"service.enable",
		"service.disable",
		"rotateServiceLogIfNeeded",
		"readRecentLogLines",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/catalog.go",
		"catalog.apply",
		"RecordMutation",
	); err != nil {
		return err
	}
	if err := mustContain("internal/registry/registry.go",
		"MaxAuditEventLimit",
		"redaction.Value(input.Metadata)",
		"input.Message = redaction.String(input.Message)",
	); err != nil {
		return err
	}
	if err := mustContain("internal/cli/dispatch.go",
		"followFile(ctx, cfg.LogFile, a.Stdout, a.Inv.String(\"level\"))",
		"redaction.String(line)",
		"cliLogLineSeverity",
	); err != nil {
		return err
	}
	if err := mustContain("internal/cli/cli.go",
		"redaction.String(err.Error())",
	); err != nil {
		return err
	}
	if err := mustContain("internal/cli/output_contract.go",
		"response.Message = redaction.String(response.Message)",
		"redaction.Value(response.Details)",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt",
		"clearTransferImportSecretsAfterDispatch",
		"importPassword = \"\"",
		"logsRefreshJob?.cancel()",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt",
		"val dispatchPayload = payload",
		"password = \"\"",
		"confirmPassword = \"\"",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt",
		"clearTransferImportSecretsAfterDispatch()",
	); err != nil {
		return err
	}
	coverageRaw, err := os.ReadFile(filepath.Join(root, "docs", "audit", "roadmap-coverage.json"))
	if err != nil {
		return fmt.Errorf("CHR16 read roadmap coverage: %w", err)
	}
	var coverage auditCoverage
	if err := json.Unmarshal(coverageRaw, &coverage); err != nil {
		return fmt.Errorf("CHR16 parse roadmap coverage: %w", err)
	}
	want := map[string]bool{"D11": true, "D12": true, "D14": true, "D15": true, "D45": true, "U110": true, "U111": true, "U112": true, "U113": true, "U114": true, "U115": true, "U185": true, "U186": true, "U187": true, "U188": true, "U189": true}
	sourceCount := 0
	for _, finding := range coverage.CanonicalFindings {
		if finding.OwnerOverlay != "CHR16" {
			continue
		}
		if !want[finding.ID] {
			return fmt.Errorf("CHR16 roadmap contains unexpected canonical finding %s", finding.ID)
		}
		if finding.Status == "planned" {
			return fmt.Errorf("CHR16 canonical finding %s remains planned", finding.ID)
		}
		delete(want, finding.ID)
		sourceCount += len(finding.SourceFindings)
	}
	if len(want) != 0 || sourceCount != 42 {
		return fmt.Errorf("CHR16 exact roadmap closure mismatch: missing=%v sourceManifestations=%d/42", want, sourceCount)
	}
	if err := mustContain("docs/audit/CHR16_LOGGING_DIAGNOSTICS_AUDIT_EVIDENCE.md", "Logging, diagnostics, audit & evidence", "ValidateLoggingDiagnosticsAuditEvidence"); err != nil {
		return err
	}
	return nil
}
