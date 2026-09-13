package repoctl

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestAuditCoverageMatchesMasterAccounting(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateAuditCoverage(root); err != nil {
		t.Fatal(err)
	}
}

func TestAuditCoverageRejectsDroppedCanonicalFinding(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(root, "docs", "audit", "roadmap-coverage.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload := map[string]any{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatal(err)
	}
	findings := payload["canonicalFindings"].([]any)
	payload["canonicalFindings"] = findings[:len(findings)-1]
	mutated, _ := json.Marshal(payload)

	tmp := t.TempDir()
	path := filepath.Join(tmp, "docs", "audit")
	if err := os.MkdirAll(path, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "roadmap-coverage.json"), mutated, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateAuditCoverage(tmp); err == nil {
		t.Fatal("expected dropped canonical finding to fail coverage validation")
	}
}
