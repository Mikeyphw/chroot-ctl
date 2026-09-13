package repoctl

import "testing"

func TestValidateLoggingDiagnosticsAuditEvidenceCHR16(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateLoggingDiagnosticsAuditEvidence(root); err != nil {
		t.Fatal(err)
	}
}
