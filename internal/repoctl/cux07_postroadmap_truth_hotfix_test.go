package repoctl

import (
	"os"
	"regexp"
	"strings"
	"testing"
)

func TestCUX07PostRoadmapTruthHotfix(t *testing.T) {
	jsb, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	bridgeb, err := os.ReadFile("../module/webroot/chrootctl.js")
	if err != nil {
		t.Fatal(err)
	}
	cssb, err := os.ReadFile("../module/webroot/index.css")
	if err != nil {
		t.Fatal(err)
	}
	htmlb, err := os.ReadFile("../module/webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	js, bridge, css, html := string(jsb), string(bridgeb), string(cssb), string(htmlb)

	if strings.Contains(js, "applyDefaultChrootToSelect") {
		t.Fatal("global default-chroot select helper must remain retired")
	}
	for _, want := range []string{"bindContextualChrootSelect", "This workspace never guesses a global target", "currentSection==='operations'||currentSection==='activity'"} {
		if !strings.Contains(js, want) {
			t.Fatalf("post-roadmap JS gap: %q", want)
		}
	}
	if strings.Contains(js, "await dashboard()") {
		t.Fatal("undefined dashboard() call remains")
	}

	queryCalls := regexp.MustCompile(`appRequest\('query','([^']+)'`).FindAllStringSubmatch(bridge, -1)
	start := strings.Index(bridge, "const APP_QUERY_ALLOW")
	end := strings.Index(bridge, "const APP_PREVIEW_ALLOW")
	if start < 0 || end <= start {
		t.Fatal("query allow-list block not found")
	}
	allow := bridge[start:end]
	for _, match := range queryCalls {
		if !strings.Contains(allow, "'"+match[1]+"'") {
			t.Fatalf("typed query %s is callable but absent from APP_QUERY_ALLOW", match[1])
		}
	}
	for _, want := range []string{"function capabilityMode(mode){return mode==='run'?'operation':mode}", "requireAllowedRun(operation)", "'transfer.import'", "'transfer.export'", "'remote.rclone.config_import'", "'operations.retry'", "'system.module_build'"} {
		if !strings.Contains(bridge, want) {
			t.Fatalf("run capability/allow-list truth gap: %q", want)
		}
	}

	for _, want := range []string{"@media(min-width:800px)", ".nav-secondary", ".primary-overflow", ".pref-compact-nav .product-nav"} {
		if !strings.Contains(css, want) {
			t.Fatalf("responsive shell gap: %q", want)
		}
	}
	for _, route := range []string{`data-route="transfer"`, `data-route="rclone"`, `data-route="activity"`, `data-route="settings"`} {
		if !strings.Contains(html, route) {
			t.Fatalf("phone overflow route missing: %s", route)
		}
	}
	for _, want := range []string{`id="home-running-count"`, "reconcileChrootContext", "else if(logs)", "classList.add('hidden')"} {
		if !strings.Contains(html+js, want) {
			t.Fatalf("post-roadmap runtime/refresh regression guard missing: %q", want)
		}
	}
}
