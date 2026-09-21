package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTMUX01BuildContract(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(root, "scripts/tmux/build-static-android-arm64.sh"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, want := range []string{"BUILD_FINGERPRINT_FILE", "build_fingerprint()", "tmux build cache verified — reusing existing artifact", "tmux legacy build verified — adopted into current build cache", "CHROOTCTL_TMUX_FORCE_REBUILD", "TMUX_VERSION=3.7c", "TMUX_SHA256=7c60cae9a0e25288e2e24750aafc9e8800fc7fd4555e447e1b29ee4201cfb3bf", "LIBEVENT_SHA256=92e6de1be9ec176428fd2367677e61ceffc2ee1cb119035037a27d346b0403bb", "NCURSES_SHA256=136d91bc269a9a5785e5f9e980bc76ab57428f604ce3e5a5a90cebc767971cc6", "NDK_REVISION=${CHROOTCTL_TMUX_NDK_REVISION:-29.0.14206865}", "bionic-static", "--enable-static", "-static", "--build-id=none", "compression\": \"none"} {
		if !strings.Contains(s, want) {
			t.Fatalf("TMUX-01 build contract missing %q", want)
		}
	}
}

func TestTMUX01DevtoolAndPackagingContract(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	checks := map[string][]string{
		".devtool.toml":                                {"scripts/tmux/**", "docs/runtime/TMUX_STATIC_RUNTIME.md"},
		"scripts/devtool/root-module-restore.sh":       {"CHROOTCTL_TMUX_FETCH_ONLY=1", "build-static-android-arm64.sh"},
		"scripts/devtool/root-module-build.sh":         {"build-static-android-arm64.sh", "CHROOTCTL_REQUIRE_TMUX=1", "CHROOTCTL_TMUX_PATH"},
		"scripts/devtool/root-module-package.sh":       {"runtime/arm64-v8a/tmux", "tmux-runtime-manifest.json", "verify-static-android-arm64.sh", "unzip -p", "tmux.sha256"},
		"scripts/devtool/root-module-lint.sh":          {"scripts/tmux/build-static-android-arm64.sh", "android-glob-compat.c", "clang -Wall -Wextra -Werror"},
		"internal/repoctl/repoctl.go":                  {"CHROOTCTL_TMUX_PATH", "tmux-runtime-manifest.json", "tmux.sha256"},
		"scripts/tmux/android-glob-compat.c":           {"CHROOTCTL_ANDROID_GLOB_COMPAT", "fnmatch", "GLOB_NOMATCH", "globfree"},
		"scripts/tmux/android-glob-compat.h":           {"int glob(", "void globfree("},
		"scripts/tmux/test-android-glob-compat.sh":     {"Android API<28 glob compatibility test passed", "space name.conf", "*.cfg"},
		"scripts/tmux/android-langinfo-compat.c":       {"chrootctl_android_nl_langinfo", "CODESET", "MB_CUR_MAX", "ASCII", "UTF-8"},
		"scripts/tmux/test-android-langinfo-compat.sh": {"android langinfo compatibility test passed"},
		"scripts/tmux/verify-static-android-arm64.sh":  {"ELF64", "AArch64", "INTERP", "(NEEDED)", "tmux-runtime-manifest.json", "Deliberately do NOT execute"},
	}
	for rel, wants := range checks {
		b, e := os.ReadFile(filepath.Join(root, rel))
		if e != nil {
			t.Fatal(e)
		}
		for _, w := range wants {
			if !strings.Contains(string(b), w) {
				t.Fatalf("%s missing %q", rel, w)
			}
		}
	}
}

func TestTMUX01VerifierNeverExecutesTarget(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(root, "scripts/tmux/verify-static-android-arm64.sh"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, forbidden := range []string{"$bin\" -V", "tmux -V", "/tmp/chrootctl-tmux", "strings \"$bin\""} {
		if strings.Contains(s, forbidden) {
			t.Fatalf("TMUX-01 verifier must not contain %q", forbidden)
		}
	}
}
