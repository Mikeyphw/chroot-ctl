package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPostCUXRuntimeAndEvidenceConvergenceContract(t *testing.T) {
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
	require := func(rel string, tokens ...string) {
		body := read(rel)
		for _, token := range tokens {
			if !strings.Contains(body, token) {
				t.Fatalf("%s missing post-CUX invariant %q", rel, token)
			}
		}
	}

	require("internal/services/lifecycle.go",
		"chmodule.ValidateInstalled(root)",
		`"state": "root_module_primary"`,
		`"enabled": active`,
	)
	if strings.Contains(read("internal/services/lifecycle.go"), "android_app_primary") {
		t.Fatal("retired Android-app-primary lifecycle state remains")
	}

	require("internal/services/release_readiness.go",
		"releaseEvidenceSchemaVersion = 4",
		`{"root_restore", "Root-module restore"}`,
		`{"root_build", "Root-module build"}`,
		`{"root_test", "Root-module tests"}`,
		`{"root_lint", "Root-module lint"}`,
		`{"root_package", "Root-module package seal"}`,
		`prov != "subprocess" && prov != "internal-check" && prov != "devtool-stage"`,
		`"installed_module"`, `"native_runtime"`,
	)
	for _, retired := range []string{"android_compileDebugKotlin", "android_testDebugUnitTest", "android_lint_configuration_seal", "android_localization_rtl"} {
		if strings.Contains(read("internal/services/release_readiness.go"), retired) {
			t.Fatalf("retired release-readiness evidence remains: %s", retired)
		}
	}

	require("internal/repoctl/root_module_evidence.go",
		"root_restore", "root_build", "root_test", "root_lint", "root_package", "devtool-stage",
		"chmodule.SealValidationEvidence",
	)
	require("internal/repoctl/seal_evidence.go",
		"legacy-final-seal-results.json",
		"Legacy repoctl final-seal evidence is intentionally repository-local",
	)
	if strings.Contains(read("internal/repoctl/seal_evidence.go"), `return "/data/adb/chrootctl/validation-results.json"`) {
		t.Fatal("legacy schema-v3 final-seal can still overwrite runtime readiness evidence")
	}
	require("scripts/devtool/root-module-package.sh",
		"root-module-evidence.sh require root_restore root_build root_test root_lint",
		"seal-root-module-evidence",
		"validation-results.json",
	)
	require("internal/module/module.go",
		"ValidateInstalled(root string)",
		"EVIDENCE_SOURCE=\"$MODDIR/config/chrootctl/validation-results.json\"",
		"post-fs-data validation-evidence-refreshed",
	)

	require("internal/bridge/backend.go",
		`ready, _ := m["ready"].(bool)`,
		`stepOK = ready`,
		`"bundled runtime is not ready"`,
	)

	devtool := read(".devtool.toml")
	packageSection := strings.Index(devtool, "package = [")
	validateSection := strings.Index(devtool, "validate = [")
	if packageSection < 0 || validateSection < 0 || packageSection > validateSection {
		t.Fatal("root-module package workflow is missing")
	}
	packageWorkflow := devtool[packageSection:validateSection]
	for _, token := range []string{`"runner:command#test"`, `"job:chrootctl-root-module-lint"`, `"runner:command#package"`} {
		if !strings.Contains(packageWorkflow, token) {
			t.Fatalf("root-module package workflow does not seal %s", token)
		}
	}
}
