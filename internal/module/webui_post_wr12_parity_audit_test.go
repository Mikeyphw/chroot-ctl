package module

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func webuiFunctionSlice(t *testing.T, source, name string) string {
	t.Helper()
	needle := "function " + name + "("
	start := strings.Index(source, needle)
	if start < 0 {
		t.Fatalf("missing WebUI function %q", name)
	}
	tail := source[start+len(needle):]
	end := len(tail)
	for _, marker := range []string{"\nexport async function ", "\nasync function ", "\nexport function ", "\nfunction "} {
		if i := strings.Index(tail, marker); i >= 0 && i < end {
			end = i
		}
	}
	return source[start : start+len(needle)+end]
}

func TestPostWR12CapabilityGateCoversEveryWebUIBridgeMode(t *testing.T) {
	root := filepath.Clean(filepath.Join("..", ".."))
	b, err := os.ReadFile(filepath.Join(root, "internal", "module", "webroot", "chrootctl.js"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)

	for _, want := range []string{
		"appRequest(mode,operation,payload={})",
		"await requireCapability(operation,mode)",
		"transferRequest(mode,operation,payload){await requireCapability(operation,mode)",
		"function requireAllowedRun(operation){if(!APP_RUN_ALLOW.has(operation))",
		"return requireCapability(operation,'run')",
	} {
		if !strings.Contains(s, want) {
			t.Fatalf("missing capability gate %q", want)
		}
	}

	runGates := []struct {
		function string
		gate     string
	}{
		{"runArtifactCleanup", "requireAllowedRun('artifacts.cleanup')"},
		{"runSnapshot", "requireAllowedRun(op)"},
		{"runUserMutation", "requireAllowedRun(op)"},
		{"runLifecycle", "requireAllowedRun(op)"},
		{"runCatalogApply", "requireAllowedRun('catalog.apply')"},
		{"runProofOperation", "requireAllowedRun(operation)"},
		{"runSimpleOperation", "requireAllowedRun(operation)"},
		{"runMaintenanceOperation", "requireAllowedRun(operation)"},
		{"runInstall", "requireAllowedRun('install.run')"},
		{"runTransfer", "requireAllowedRun(operation)"},
		{"importRcloneConfig", "requireAllowedRun('remote.rclone.config_import')"},
		{"retryOperation", "requireAllowedRun('operations.retry')"},
		{"runServiceMutation", "requireAllowedRun(op)"},
		{"runModuleBuild", "requireAllowedRun('system.module_build')"},
		{"runSessionMutation", "requireAllowedRun(operation)"},
	}
	for _, tc := range runGates {
		body := webuiFunctionSlice(t, s, tc.function)
		if !strings.Contains(body, tc.gate) {
			t.Fatalf("%s must use centralized run gate %q", tc.function, tc.gate)
		}
	}

	// Every app/run path must pass through the one centralized allow-list +
	// capability-mode gate. Query and preview requests retain their own mode gate.
	if strings.Count(s, "APP_RUN_ALLOW.has(") != 1 {
		t.Fatalf("APP_RUN_ALLOW must be enforced only by requireAllowedRun; found %d call sites", strings.Count(s, "APP_RUN_ALLOW.has("))
	}
	if strings.Count(s, "requireCapability(operation,'run')") != 1 {
		t.Fatal("run capability normalization must be centralized in requireAllowedRun")
	}
	for _, forbidden := range []string{
		"requireCapability(op,'run')",
		"requireCapability('install.run','run')",
		"requireCapability('artifacts.cleanup','run')",
	} {
		if strings.Contains(s, forbidden) {
			t.Fatalf("direct run capability check bypasses the centralized run allow-list: %q", forbidden)
		}
	}

	if strings.Count(s, "export async function runSmoke(") != 1 {
		t.Fatalf("runSmoke must have one authoritative implementation")
	}
	if strings.Count(s, "export async function exportDebugEvidence(") != 1 {
		t.Fatalf("exportDebugEvidence must have one authoritative implementation")
	}
	if !strings.Contains(s, "if(event?.protocolVersion!==1)throw new ChrootCtlError('Bridge event protocol mismatch'") {
		t.Fatal("streaming operation protocol gate missing")
	}
}
