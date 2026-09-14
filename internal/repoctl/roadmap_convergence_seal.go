package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateRoadmapConvergenceSeal is the post-roadmap CHR23 regression contract.
// It verifies that later Android seal overlays did not weaken the CHR01-CHR20
// composite gate and that CHR16's diagnostics/audit promises are closed in
// both implementation and the machine-readable coverage ledger.
func ValidateRoadmapConvergenceSeal(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			return "", fmt.Errorf("CHR23 read %s: %w", rel, err)
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
				return fmt.Errorf("CHR23 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}

	if err := mustContain(".devtool-artifact/validate.sh",
		"go run ./cmd/repoctl validate",
		":chrootctlAndroidAppSeal",
		":chrootctlAndroidLintConfigurationSeal",
	); err != nil {
		return err
	}
	if err := mustContain(".devtool.toml",
		"preflight = [\":chrootctlAndroidAppSeal\"]",
		"lint = [\":chrootctlAndroidLintConfigurationSeal\"]",
		"test_command = \"go run ./cmd/repoctl validate\"",
	); err != nil {
		return err
	}
	if err := mustContain(".github/workflows/ci.yml", "--continue :chrootctlAndroidAppSeal"); err != nil {
		return err
	}
	if err := mustContain("internal/repoctl/final_seal.go",
		`":chrootctlAndroidAppSeal"`,
		`"android_lint_configuration_seal"`,
	); err != nil {
		return err
	}
	for _, rel := range []string{"internal/repoctl/seal_evidence.go", "internal/services/release_readiness.go"} {
		if err := mustContain(rel, "android_lint_configuration_seal"); err != nil {
			return err
		}
		text, _ := read(rel)
		if strings.Contains(text, "android_lintDebug") {
			return fmt.Errorf("CHR23 %s still uses retired android_lintDebug evidence id", rel)
		}
	}

	if err := mustContain("internal/services/audit.go",
		"RecordMutation",
		"Actor: redaction.String(actor)",
		"Target: redaction.String(target)",
		"Message: redaction.String(message)",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/users.go",
		"user.add", "user.remove", "user.set_password", "user.set_shell", "user.set_sudo", "user.sync_id",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/units.go",
		"service.start", "service.stop", "service.restart", "service.enable", "service.disable",
		"rotateServiceLogIfNeeded", "readRecentLogLines",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/catalog.go", "catalog.apply", "RecordMutation"); err != nil {
		return err
	}
	if err := mustContain("internal/services/system.go",
		"readRecentLogLines", "tail + 1", "non-symlink", "syscall.O_NOFOLLOW", "redaction.String",
	); err != nil {
		return err
	}
	if err := mustContain("internal/cli/output_contract.go",
		"response.Message = redaction.String(response.Message)", "redaction.Value(response.Details)",
	); err != nil {
		return err
	}
	if err := mustContain("internal/cli/cli.go", "redaction.String(err.Error())"); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt", "logsRefreshJob?.cancel()"); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt",
		"val dispatchPayload = payload", "password = \"\"", "confirmPassword = \"\"",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicy.kt", "android:chrootctlAndroidAppSeal"); err != nil {
		return err
	}

	coverageRaw, err := os.ReadFile(filepath.Join(root, "docs", "audit", "roadmap-coverage.json"))
	if err != nil {
		return fmt.Errorf("CHR23 read roadmap coverage: %w", err)
	}
	var coverage auditCoverage
	if err := json.Unmarshal(coverageRaw, &coverage); err != nil {
		return fmt.Errorf("CHR23 parse roadmap coverage: %w", err)
	}
	if len(coverage.CanonicalFindings) != 272 || coverage.SourceFindingCount != 609 {
		return fmt.Errorf("CHR23 roadmap cardinality changed: canonical=%d/272 source=%d/609", len(coverage.CanonicalFindings), coverage.SourceFindingCount)
	}
	chr16Count, chr16Sources := 0, 0
	for _, finding := range coverage.CanonicalFindings {
		if finding.Status == "planned" {
			return fmt.Errorf("CHR23 canonical finding %s remains planned", finding.ID)
		}
		if finding.OwnerOverlay == "CHR16" {
			chr16Count++
			chr16Sources += len(finding.SourceFindings)
		}
	}
	if chr16Count != 16 || chr16Sources != 42 {
		return fmt.Errorf("CHR23 CHR16 closure mismatch: canonical=%d/16 source=%d/42", chr16Count, chr16Sources)
	}

	for _, rel := range []string{
		"internal/cli/redaction_chr23_test.go",
		"internal/services/logging_diagnostics_chr23_test.go",
		"android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/AndroidAppSealPolicyTest.kt",
		"docs/audit/CHR23_ROADMAP_CONVERGENCE_SEAL.md",
	} {
		if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(rel))); err != nil {
			return fmt.Errorf("CHR23 required regression artifact %s missing: %w", rel, err)
		}
	}
	return nil
}
