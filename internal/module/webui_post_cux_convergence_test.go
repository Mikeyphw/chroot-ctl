package module

import (
	"os"
	"strings"
	"testing"
)

func TestPostCUXWebUIConvergenceContract(t *testing.T) {
	htmlRaw, err := os.ReadFile("webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	jsRaw, err := os.ReadFile("webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	bridgeRaw, err := os.ReadFile("webroot/chrootctl.js")
	if err != nil {
		t.Fatal(err)
	}
	html, js, bridge := string(htmlRaw), string(jsRaw), string(bridgeRaw)

	hero := strings.Index(html, `<section class="hero">`)
	home := strings.Index(html, `id="home-panel"`)
	if hero < 0 || home < 0 || hero > home {
		t.Fatal("Home route hero must precede dashboard content")
	}

	for _, retired := range []string{
		`id="readiness-panel"`, `id="readiness-state"`, `id="debug-export-review"`, `id="smoke-state"`,
	} {
		if strings.Contains(html, retired) {
			t.Fatalf("retired duplicate readiness/debug surface remains %q", retired)
		}
	}
	if strings.Index(html, `id="diagnostics-panel"`) > strings.Index(html, `id="compatibility-state"`) {
		t.Fatal("compatibility contract must live inside System diagnostics")
	}
	for _, want := range []string{
		`id="diag-smoke-cancel" class="button danger hidden"`,
		`Cancel running suite`,
	} {
		if !strings.Contains(html, want) {
			t.Fatalf("smoke idle-state contract missing %q", want)
		}
	}
	for _, want := range []string{
		"Promise.allSettled([releaseReadiness(),debugProbes(group),debugTimeline(50),smokeLastResult()])",
		"technicalError('Release readiness unavailable'",
		"technicalError('Debug probes unavailable'",
		"technicalError('Audit timeline unavailable'",
		"technicalError('Smoke result unavailable'",
		"$('sessions-runtime').textContent='Unavailable'",
		"$('session-create').disabled=true",
		"rcloneButton.textContent=rcloneReady?'Open Rclone':'View Rclone status'",
		"window.scrollTo({top:0,left:0,behavior:'instant'})",
	} {
		if !strings.Contains(js, want) {
			t.Fatalf("post-CUX UI convergence contract missing %q", want)
		}
	}
	for _, retired := range []string{"loadReadiness", "readinessState", "debug-export-review", "$('readiness-panel')"} {
		if strings.Contains(js, retired) {
			t.Fatalf("retired readiness/debug implementation remains %q", retired)
		}
	}
	for _, want := range []string{
		"technicalExcerpt(value,max=4096)",
		"$('home-chroot-count').textContent='Unavailable'",
		"$('home-running-count').textContent='Unavailable'",
	} {
		if !strings.Contains(js, want) {
			t.Fatalf("post-CUX truthful error-state contract missing %q", want)
		}
	}
	if strings.Contains(js, "Bridge returned invalid JSON") {
		t.Fatal("raw generic invalid-JSON UI copy remains in index.js")
	}
	for _, want := range []string{
		"let selectedExecutable=null",
		"serializeKernelSU",
		"app','capabilities",
		"selectedExecutable=executable",
		"Bridge response for ${operation||'operation'} was not valid JSON",
		"function requestBackendLabel()",
		"function annotateRequestError(error,operation)",
		"Standalone backend returned invalid JSON",
	} {
		if !strings.Contains(bridge, want) {
			t.Fatalf("post-CUX bridge convergence contract missing %q", want)
		}
	}
}
