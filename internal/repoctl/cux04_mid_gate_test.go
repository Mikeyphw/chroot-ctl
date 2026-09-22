package repoctl

import (
	"os"
	"regexp"
	"strings"
	"testing"
)

func TestCUX04FunctionalConvergenceMidGate(t *testing.T) {
	htmlb, err := os.ReadFile("../module/webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	jsb, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	bridgeb, err := os.ReadFile("../module/webroot/chrootctl.js")
	if err != nil {
		t.Fatal(err)
	}
	html, js, bridge := string(htmlb), string(jsb), string(bridgeb)
	for _, want := range []string{"const appState=", "function withDeadline", "STARTUP_TIMEOUT_MS=15000", "persistRoute(name)", "showSection(restoredRoute())", "appState.backend='error'"} {
		if !strings.Contains(js, want) {
			t.Fatalf("CUX04 startup/state invariant missing %q", want)
		}
	}
	start := strings.Index(js, "async function bootstrapBackend()")
	if start < 0 {
		t.Fatal("bootstrapBackend declaration not found")
	}
	openRel := strings.Index(js[start:], "{")
	if openRel < 0 {
		t.Fatal("bootstrapBackend opening brace not found")
	}
	open := start + openRel
	depth, close := 0, -1
	for i := open; i < len(js); i++ {
		switch js[i] {
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				close = i + 1
				i = len(js)
			}
		}
	}
	if close < 0 {
		t.Fatal("bootstrapBackend closing brace not found")
	}
	bootstrap := js[start:close]
	if strings.Contains(bootstrap, "showSection('chroots')") {
		t.Fatal("startup still hard-resets navigation to Chroots")
	}
	for _, want := range []string{"standaloneHTTP = loopbackHTTP && !isKernelSUAvailable()", "new URL(path,window.location.origin)", "credentials:'same-origin'", "WEBUI_BACKEND_TIMEOUT"} {
		if !strings.Contains(bridge, want) {
			t.Fatalf("CUX04 transport invariant missing %q", want)
		}
	}
	ids := regexp.MustCompile(`id="([^"]+)"`).FindAllStringSubmatch(html, -1)
	seen := map[string]bool{}
	for _, m := range ids {
		if seen[m[1]] {
			t.Fatalf("duplicate HTML id %q", m[1])
		}
		seen[m[1]] = true
	}
	for _, op := range []string{"chroots.list", "chroots.get", "system.status", "storage.status", "snapshots.list", "artifacts.list", "transfer.artifact_root", "debug.probes", "debug.timeline", "release.readiness", "smoke.plan", "smoke.last_result"} {
		if !strings.Contains(bridge, "'"+op+"'") {
			t.Fatalf("diagnostic query missing from WebUI contract: %s", op)
		}
	}
	queryCall := regexp.MustCompile(`appRequest\('query','([^']+)'`).FindAllStringSubmatch(bridge, -1)
	allowBlock := bridge[strings.Index(bridge, "const APP_QUERY_ALLOW"):strings.Index(bridge, "const APP_PREVIEW_ALLOW")]
	for _, match := range queryCall {
		if !strings.Contains(allowBlock, "'"+match[1]+"'") {
			t.Fatalf("query %s is shipped but missing from APP_QUERY_ALLOW", match[1])
		}
	}
	if !strings.Contains(bridge, "mode==='run'?'operation':mode") {
		t.Fatal("transport run mode is not normalized to backend capability mode operation")
	}

}
