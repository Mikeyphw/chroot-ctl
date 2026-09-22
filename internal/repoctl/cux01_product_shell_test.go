package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCUX01ProductShell(t *testing.T) {
	root := filepath.Join("..", "..")
	read := func(name string) string {
		b, err := os.ReadFile(filepath.Join(root, name))
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	html := read("internal/module/webroot/index.html")
	css := read("internal/module/webroot/index.css")
	js := read("internal/module/webroot/index.js")
	for _, domain := range []string{"Home", "Chroots", "Terminal", "Jobs", "Transfer", "Rclone", "Activity", "System"} {
		if !strings.Contains(html, ">"+domain+"</span>") {
			t.Fatalf("missing primary domain %s", domain)
		}
	}
	if strings.Contains(html, "<p class=\"eyebrow\">KernelSU WebUI</p>") {
		t.Fatal("transport must not be product branding")
	}
	for _, legacy := range []string{"Create chroot", "Users", "Services", "Snapshots", "Storage", "Diagnostics"} {
		if !strings.Contains(html, ">"+legacy+"</button>") {
			t.Fatalf("existing workspace lost from contextual tools: %s", legacy)
		}
	}
	for _, want := range []string{"@media(min-width:800px)", ".product-nav", ".nav-secondary", ".primary-overflow", ".tools-sheet", "--radius-hero:28px"} {
		if !strings.Contains(css, want) {
			t.Fatalf("missing responsive/design-system invariant %q", want)
		}
	}
	for _, want := range []string{"let currentSection='home'", "toolsSheet.showModal()", "showSection(b.dataset.route)", "pref-compact-nav"} {
		if !strings.Contains(js, want) {
			t.Fatalf("missing shell behavior %q", want)
		}
	}
}
