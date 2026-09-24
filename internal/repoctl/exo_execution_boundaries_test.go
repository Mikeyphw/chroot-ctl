package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestEXOExecutionBoundaryConvergence(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	read := func(rel string) string {
		raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			t.Fatal(err)
		}
		return string(raw)
	}

	cfg := read(".devtool.toml")
	for _, token := range []string{
		"job:chrootctl-root-build-runtime",
		"job:chrootctl-root-build-module",
		"job:chrootctl-root-test-webui",
		"job:chrootctl-root-test-go",
		"job:chrootctl-root-test-tmux",
		"job:chrootctl-root-lint-go",
		"job:chrootctl-root-lint-native",
		"job:chrootctl-root-package-preflight",
		"job:chrootctl-root-package-runtime",
		"job:chrootctl-root-package-webui",
		"job:chrootctl-root-package-evidence",
		"validate-step", "metadata = { read_only = true }",
	} {
		if !strings.Contains(cfg, token) {
			t.Fatalf("Devtool EXO contract missing %q", token)
		}
	}
	if strings.Contains(cfg, `validate = ["runner:command#test"]`) {
		t.Fatal("release validation regressed to one opaque command node")
	}
	artifactValidator := read(".devtool-artifact/validate.sh")
	for _, retired := range []string{"android/gradlew", "chrootctlAndroidAppSeal", "chrootctlAndroidLintConfigurationSeal"} {
		if strings.Contains(artifactValidator, retired) {
			t.Fatalf("active artifact validator still references retired Android gate %q", retired)
		}
	}
	finalSeal := read("internal/repoctl/final_seal.go")
	if strings.Contains(finalSeal, "chrootctlAndroidAppSeal") || strings.Contains(finalSeal, `filepath.Join(root, "android")`) {
		t.Fatal("legacy final-seal still executes the retired standalone Android product")
	}
	evidence := read("internal/repoctl/seal_evidence.go")
	for _, retired := range []string{"android_compileDebugKotlin", "android_testDebugUnitTest", "android_lint_configuration_seal"} {
		if strings.Contains(strings.Split(evidence, "func validationRunID")[0], retired) {
			t.Fatalf("legacy final-seal evidence still requires retired Android check %q", retired)
		}
	}
}

func TestValidationStepSurfaceMatchesCurrentValidateContract(t *testing.T) {
	got := ValidationStepNames()
	want := []string{
		"test-seal", "repository-purity", "audit-coverage", "root-module-retirement",
		"contract-generation", "cli-contract", "mutation-engine", "crud-atomicity",
		"clipboard-integration", "frozen-live-contracts",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("validation step surface drifted:\n got=%v\nwant=%v", got, want)
	}
}
