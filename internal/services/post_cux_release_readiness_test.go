package services

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPostCUXReleaseReadinessUsesRootModuleEvidenceOnly(t *testing.T) {
	c := testContainer(t)
	repo := findRepoRoot()
	compat, err := os.ReadFile(filepath.Join(repo, "docs", "release", "compatibility-manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(compat)
	checks := map[string]any{}
	for _, id := range []string{"root_restore", "root_build", "root_test", "root_lint", "root_package"} {
		checks[id] = map[string]any{"status": "pass", "command": "devtool " + id, "provenance": "devtool-stage", "exitCode": 0, "recordedAt": time.Now().Unix()}
	}
	payload := map[string]any{
		"schemaVersion":               4,
		"generatedAt":                 time.Now().Unix(),
		"validationRunId":             "test-root-module",
		"sourceCommit":                "",
		"sourceTree":                  "",
		"compatibilityManifestSha256": hex.EncodeToString(sum[:]),
		"checks":                      checks,
	}
	raw, _ := json.Marshal(payload)
	path := filepath.Join(t.TempDir(), "validation-results.json")
	if err := os.WriteFile(path, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CHROOTCTL_VALIDATION_RESULTS", path)
	status := c.ReleaseReadiness().Status()
	if status["evidencePresent"] != true {
		t.Fatalf("schema-v4 evidence should be accepted: %+v", status)
	}
	rows, ok := status["checks"].([]map[string]any)
	if !ok {
		t.Fatalf("unexpected readiness checks type: %T", status["checks"])
	}
	seen := map[string]bool{}
	for _, row := range rows {
		seen[stringValue(row["id"])] = true
	}
	for _, id := range []string{"root_restore", "root_build", "root_test", "root_lint", "root_package", "installed_module", "native_runtime"} {
		if !seen[id] {
			t.Fatalf("missing current root-module readiness check %s", id)
		}
	}
	for _, retired := range []string{"android_compileDebugKotlin", "android_testDebugUnitTest", "android_lint_configuration_seal", "android_localization_rtl"} {
		if seen[retired] {
			t.Fatalf("retired Android readiness check leaked into current product: %s", retired)
		}
	}
}
