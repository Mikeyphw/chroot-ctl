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
	for _, token := range []string{"loadSettings", "reviewStartupModule", "buildStartupModule", "loadSettingsMounts", "SETTINGS_PREF_KEY", "refreshOperationEvents", "syncLogsFollow", "copyDiagnosticText"} {
		if !strings.Contains(js, token) {
			t.Fatalf("missing settings UI contract %s", token)
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
	if !strings.Contains(html, "connect-src 'none'") {
		t.Fatal("final WebUI CSP must keep direct network connections disabled")
	}
}
