package module

import (
	"os"
	"strings"
	"testing"
)

func TestWebUIFinalConvergenceSeal(t *testing.T) {
	htmlBytes, err := os.ReadFile("webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	jsBytes, err := os.ReadFile("webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	bridgeBytes, err := os.ReadFile("webroot/chrootctl.js")
	if err != nil {
		t.Fatal(err)
	}
	cssBytes, err := os.ReadFile("webroot/index.css")
	if err != nil {
		t.Fatal(err)
	}
	html, js, bridge, css := string(htmlBytes), string(jsBytes), string(bridgeBytes), string(cssBytes)
	for _, id := range []string{"chroots-panel", "create-panel", "transfer-panel", "rclone-panel", "operations-panel", "logs-panel", "settings-panel"} {
		if !strings.Contains(html, `id="`+id+`"`) {
			t.Fatalf("missing final WebUI section %s", id)
		}
	}
	for _, token := range []string{"system.runtime", "system.module_status", "system.module_build_preview", "system.module_build", "previewModuleBuild", "runModuleBuild"} {
		if !strings.Contains(bridge, token) {
			t.Fatalf("missing typed settings/startup bridge token %s", token)
		}
	}
	for _, token := range []string{"loadSettings", "reviewStartupModule", "buildStartupModule", "loadSettingsMounts", "SETTINGS_PREF_KEY", "refreshOperationEvents", "syncLogsFollow", "copyDiagnosticText", "transferPathAllowed", "importRemoteHandoff", "exportRemoteHandoff", "PRIVATE_DOCTOR_CHECKS", "diagnosticFailure", "refreshRuntimeDiagnostics", "preferredChrootName", "event?.payload", "files_done", "rate_bytes_per_second"} {
		if !strings.Contains(js, token) {
			t.Fatalf("missing settings UI contract %s", token)
		}
	}
	for _, token := range []string{"logs-runtime-state", "logs-runtime-facts"} {
		if !strings.Contains(html, `id="`+token+`"`) {
			t.Fatalf("missing Logs runtime diagnostic surface %s", token)
		}
	}
	for _, token := range []string{"if(d.ok===true)transferState.importPayload=p;else{scrubTransferPayload(p);clearTransferPassword('import');transferState.importPayload=null}", "if(d.ok===true)transferState.exportPayload=p;else{scrubTransferPayload(p);clearTransferPassword('export');transferState.exportPayload=null}"} {
		if !strings.Contains(js, token) {
			t.Fatalf("blocked transfer preview must scrub retained password payload: %s", token)
		}
	}
	for _, token := range []string{"pref-large-text", "pref-reduce-motion", "pref-compact-nav", "focus-visible"} {
		if !strings.Contains(css, token) {
			t.Fatalf("missing final accessibility contract %s", token)
		}
	}
	for _, forbidden := range []string{"eval(", "new Function", "sh -c", "su -c"} {
		if strings.Contains(bridge, forbidden) || strings.Contains(js, forbidden) {
			t.Fatalf("unsafe WebUI execution token present: %s", forbidden)
		}
	}
	if !strings.Contains(html, "connect-src 'self'") {
		t.Fatal("final WebUI CSP must allow only same-origin standalone backend connections")
	}
	if strings.Contains(html, "connect-src 'none'") {
		t.Fatal("standalone WebUI CSP must not block its own same-origin typed API")
	}
}
