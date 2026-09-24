package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRootModuleDevtoolLifecycleScripts(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	cfg, err := os.ReadFile(filepath.Join(root, ".devtool.toml"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(cfg)
	for _, want := range []string{
		`restore_command = "scripts/devtool/root-module-restore.sh"`,
		`build_command = "scripts/devtool/root-module-build.sh"`,
		`test_command = "scripts/devtool/root-module-test.sh"`,
		`package_command = "scripts/devtool/root-module-package.sh"`,
		`"job:chrootctl-root-lint-go"`,
		`"job:chrootctl-root-lint-native"`,
		`"job:chrootctl-root-package-evidence"`,
		`run = ["job:chrootctl-root-module-install"]`,
	} {
		if !strings.Contains(s, want) {
			t.Fatalf("missing Devtool lifecycle contract %q", want)
		}
	}
	for _, name := range []string{"restore", "build", "test", "lint", "package", "install", "stage"} {
		p := filepath.Join(root, "scripts", "devtool", "root-module-"+name+".sh")
		st, err := os.Stat(p)
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode()&0111 == 0 {
			t.Fatalf("%s is not executable", p)
		}
	}
}

func TestRootModuleInstallRequiresRootDiscoveredKernelSU(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(root, "scripts", "devtool", "root-module-install.sh"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, want := range []string{
		`su -c 'command -v ksud 2>/dev/null'`,
		`case "$KSUD" in`,
		`su -c "[ -f '$KSUD' ] && [ -x '$KSUD' ]"`,
		`exec su -c "'$KSUD' module install '$ABS'"`,
	} {
		if !strings.Contains(s, want) {
			t.Fatalf("missing strict KernelSU install contract %q", want)
		}
	}
}
