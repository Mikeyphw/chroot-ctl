package module

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestRootModuleRotatingLoggingContract(t *testing.T) {
	if !strings.Contains(logHelper(), "/data/local/tmp/chrootctl") || !strings.Contains(logHelper(), "KEEP=") {
		t.Fatal("log helper contract missing")
	}
	for name, raw := range map[string]string{"installer": customize(), "postfs": postFS(), "service": service(nil), "helper": helper(), "launcher": launcher(), "uninstall": uninstall()} {
		if !strings.Contains(raw, "chrootctl-log-helper") {
			t.Fatalf("%s does not use packaged log helper", name)
		}
	}
	raw := launcher()
	for _, want := range []string{`transport "invoke command=$COMMAND subcommand=$SUBCOMMAND argc=$#"`, `COMMAND="${1:-none}"`} {
		if !strings.Contains(raw, want) {
			t.Fatalf("launcher missing safe transport log %q", want)
		}
	}
	if ModuleVersion != "1.3.6" || ModuleVersionCode != 21 {
		t.Fatalf("module version=%s/%d", ModuleVersion, ModuleVersionCode)
	}
}

func TestModuleShellLogHelperRotatesFiveBackups(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "log-helper")
	if err := os.WriteFile(script, []byte(logHelper()), 0755); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 9; i++ {
		cmd := exec.Command("sh", script, "module", strings.Repeat("x", 80))
		cmd.Env = append(os.Environ(), "CHROOTCTL_LOG_ROOT="+dir, "CHROOTCTL_LOG_MAX_BYTES=64", "CHROOTCTL_LOG_KEEP=5")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("run %d: %v: %s", i, err, out)
		}
	}
	for i := 1; i <= 5; i++ {
		if _, err := os.Stat(filepath.Join(dir, "module.log."+string(rune('0'+i)))); err != nil {
			t.Fatalf("backup %d missing: %v", i, err)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "module.log.6")); !os.IsNotExist(err) {
		t.Fatalf("unexpected sixth backup: %v", err)
	}
}
