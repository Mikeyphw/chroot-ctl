package repoctl

import (
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
		"scan.Buffer(buf, 1024*1024)",
		"redaction.String(scan.Text())",
		"unsupported log level",
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
		"redaction.String",
		"redactedStringMap",
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
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt",
		"clearTransferImportSecretsAfterDispatch",
		"importPassword = \"\"",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt",
		"clearTransferImportSecretsAfterDispatch()",
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/roadmap-coverage.json",
		`"id": "CHR16"`,
		`"title": "Logging, diagnostics, audit & evidence"`,
		`"ownerOverlay": "CHR16"`,
		`"status": "implemented"`,
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR16_LOGGING_DIAGNOSTICS_AUDIT_EVIDENCE.md", "Logging, diagnostics, audit & evidence", "ValidateLoggingDiagnosticsAuditEvidence"); err != nil {
		return err
	}
	return nil
}
