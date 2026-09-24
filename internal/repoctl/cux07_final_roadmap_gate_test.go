package repoctl

import (
	"os"
	"regexp"
	"strings"
	"testing"
)

func TestCUX07FinalRoadmapGate(t *testing.T) {
	htmlb, err := os.ReadFile("../module/webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	jsb, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	cssb, err := os.ReadFile("../module/webroot/index.css")
	if err != nil {
		t.Fatal(err)
	}
	h, j, c := string(htmlb), string(jsb), string(cssb)
	routes := []string{"home", "chroots", "sessions", "operations", "transfer", "rclone", "activity", "settings"}
	for _, r := range routes {
		if !strings.Contains(h, `data-section="`+r+`"`) {
			t.Fatalf("primary route %s missing", r)
		}
	}
	// Logs is a System child route, but retains a data-section marker for the longstanding WebUI foundation contract.
	if !strings.Contains(h, `data-route="logs" data-section="logs"`) {
		t.Fatal("System Logs child route is missing its compatibility section marker")
	}
	panels := []string{"home", "chroots", "create", "users", "services", "snapshots", "storage", "catalog", "maintenance", "diagnostics", "transfer", "rclone", "sessions", "operations", "activity", "logs", "settings", "placeholder"}
	for _, p := range panels {
		if !strings.Contains(h, `id="`+p+`-panel"`) {
			t.Fatalf("panel %s missing", p)
		}
		if !strings.Contains(j, `$('`+p+`-panel').classList.toggle('hidden',!`) {
			t.Fatalf("panel %s is not explicitly routed", p)
		}
	}
	if strings.Contains(h, `id="readiness-panel"`) || strings.Contains(j, `$('readiness-panel')`) {
		t.Fatal("retired duplicate readiness panel remains after System diagnostics convergence")
	}
	if !strings.Contains(j, "if(name==='readiness')name='diagnostics'") {
		t.Fatal("legacy readiness route does not redirect into System diagnostics")
	}
	for _, want := range []string{"const appState=", "bootstrapBackend()", "restoredRoute()", "bindContextualChrootSelect", "createSession(", "captureSession(", "inputSession(", "detachSession(", "killSession(", "operationCard", "activeJob", "sectionOwnsRefresh", "rcloneStatus()", "currentSection==='operations'||currentSection==='activity'"} {
		if !strings.Contains(j, want) {
			t.Fatalf("final JS contract missing %q", want)
		}
	}
	for _, want := range []string{"Skip to main content", "Selected chroot", "Move chroots without guessing", "Browse first, transfer second", "Configuration, runtime and diagnostics"} {
		if !strings.Contains(h, want) {
			t.Fatalf("final product contract missing %q", want)
		}
	}
	for _, want := range []string{".skip-link", ":focus-visible", "min-height:44px"} {
		if !strings.Contains(c, want) {
			t.Fatalf("accessibility contract missing %q", want)
		}
	}
	if strings.Contains(h, "KERNELSU WEBUI") {
		t.Fatal("transport branding leaked into product shell")
	}
	if regexp.MustCompile(`(?i)(execCommand|rawShell|tmux\\s+-L)`).MatchString(j) {
		t.Fatal("frontend contains forbidden raw privileged execution path")
	}
	if !strings.Contains(j, "activity=name==='activity'") || !strings.Contains(j, "!operations&&!activity&&!logs") {
		t.Fatal("Activity route can fall through to placeholder")
	}
	if strings.Contains(j, "applyDefaultChrootToSelect") {
		t.Fatal("final tree reintroduced the retired global chroot-selection helper")
	}
	if strings.Contains(j, "await dashboard()") {
		t.Fatal("diagnostics smoke target path calls undefined dashboard()")
	}
	bridgeb, err := os.ReadFile("../module/webroot/chrootctl.js")
	if err != nil {
		t.Fatal(err)
	}
	bridge := string(bridgeb)
	for _, op := range []string{"chroots.list", "chroots.get", "system.status", "storage.status", "snapshots.list", "artifacts.list", "transfer.artifact_root", "smoke.plan"} {
		if !strings.Contains(bridge, "'"+op+"'") {
			t.Fatalf("final typed transport allow-list missing %s", op)
		}
	}
	pkg, err := os.ReadFile("../../scripts/devtool/root-module-stage.sh")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"runtime/arm64-v8a/chrootctl", "runtime/arm64-v8a/runtime-manifest.json", "runtime/arm64-v8a/rclone", "config/chrootctl/runtime-executables.list", "restore_runtime_exec_modes", "runtime_execs_ready", "rclone_tree_sha", "rclone_zip_sha"} {
		if !strings.Contains(string(pkg), want) {
			t.Fatalf("final package seal missing optional rclone proof %q", want)
		}
	}

}
