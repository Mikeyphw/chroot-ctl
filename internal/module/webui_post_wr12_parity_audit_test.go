package module

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPostWR12CapabilityGateCoversEveryWebUIBridgeMode(t *testing.T) {
	root := filepath.Clean(filepath.Join("..", ".."))
	b, err := os.ReadFile(filepath.Join(root, "internal", "module", "webroot", "chrootctl.js"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	required := []string{
		"appRequest(mode,operation,payload={})", "await requireCapability(operation,mode)",
		"transferRequest(mode,operation,payload){await requireCapability(operation,mode)",
		"await requireCapability('artifacts.cleanup','run')", "await requireCapability(op,'run');const payload={name:safeName(name),snapshot",
		"op=USER_ACTIONS[action];await requireCapability(op,'run')", "await requireCapability(op,'run');\n  const payload={name:safeName(name)}",
		"await requireCapability('catalog.apply','run')", "runSimpleOperation(operation,payload,handlers={}){await requireCapability(operation,'run')",
		"runMaintenanceOperation(operation,payload,preview,handlers={}){ await requireCapability(operation,'run')",
		"await requireCapability('install.run','run')", "await requireCapability(operation,'run');const args=['app','run'",
		"await requireCapability('remote.rclone.config_import','run')", "await requireCapability('operations.retry','run')",
		"await requireCapability(op,'run');for(const k of ['previewId'", "await requireCapability('system.module_build','run')",
	}
	for _, want := range required {
		if !strings.Contains(s, want) {
			t.Fatalf("missing capability gate %q", want)
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
