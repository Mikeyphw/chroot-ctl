package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTmux07ReleaseSeal(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	checks := map[string][]string{
		"scripts/tmux/device-release-smoke.sh":        {"tmux 3.7c", "sessions create", "sessions capture", "sessions detach", "sessions reconcile", "sessions kill", "mode 0700", "TMUX-07 DEVICE SMOKE PASS"},
		"docs/runtime/TMUX_RELEASE_SEAL.md":           {"c753b02433e55e8d3b75507aa65f11caa63614a09dd66bffa12295dceb1439b6", "does **not** claim tmux sessions survive reboot", "/data/adb/chrootctl/runtime/tmux", "real-device smoke evidence"},
		"scripts/devtool/root-module-package.sh":      {"runtime/arm64-v8a/tmux", "tmux-runtime-manifest.json", "tmux.sha256", "verify-static-android-arm64.sh", "unzip -p"},
		"scripts/tmux/verify-static-android-arm64.sh": {"ELF64", "AArch64", "INTERP", "(NEEDED)", `"version": "3.7c"`},
		"internal/tmuxruntime/runtime.go":             {`DefaultStateRoot = "/data/adb/chrootctl/runtime/tmux"`, "0700"},
		"internal/tmuxruntime/session.go":             {"deterministicID", "maxCaptureBytes", "context.WithTimeout"},
		"internal/tmuxruntime/jobs.go":                {"recovered", "lost"},
		"internal/module/webroot/index.js":            {"attachSession", "refreshTerminal", "terminal-input", "Recovery needed"},
	}
	for rel, wants := range checks {
		b, e := os.ReadFile(filepath.Join(root, rel))
		if e != nil {
			t.Fatal(e)
		}
		s := string(b)
		for _, w := range wants {
			if !strings.Contains(s, w) {
				t.Fatalf("%s missing %q", rel, w)
			}
		}
	}
}

func TestTmux07NoWorldWritableRuntimeContract(t *testing.T) {
	root, _ := repoRoot()
	b, err := os.ReadFile(filepath.Join(root, "internal/tmuxruntime/runtime.go"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	if strings.Contains(s, "0777") || strings.Contains(s, "0666") {
		t.Fatal("tmux runtime authority must not create world-writable state")
	}
	for _, want := range []string{"os.MkdirAll(d, 0700)", "os.Chmod(d, 0700)"} {
		if !strings.Contains(s, want) {
			t.Fatalf("runtime permission seal missing %q", want)
		}
	}
}
