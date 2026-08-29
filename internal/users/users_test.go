package users

import (
	"chrootctl/internal/config"
	sys "chrootctl/internal/system"
	"os"
	"path/filepath"
	"testing"
)

func TestListAndPasswordValidation(t *testing.T) {
	d := t.TempDir()
	cfg := config.Default(config.RuntimeContext{Home: d})
	cfg.ChrootRoot = d
	cfg.DistroName = "x"
	p := filepath.Join(cfg.ChrootBase(), "etc")
	_ = os.MkdirAll(p, 0o755)
	_ = os.WriteFile(filepath.Join(p, "passwd"), []byte("mike:x:1000:1000::/home/mike:/bin/bash\n"), 0o644)
	m := Manager{Config: cfg, Runner: &sys.Runner{DryRun: true}}
	u, e := m.List()
	if e != nil || len(u) != 1 || u[0].Username != "mike" {
		t.Fatalf("%+v %v", u, e)
	}
	if _, e = ValidatePassword("a:b"); e == nil {
		t.Fatal("expected")
	}
	if _, e = validShell("../x"); e == nil {
		t.Fatal("expected")
	}
}
func TestIdentityRows(t *testing.T) {
	p := filepath.Join(t.TempDir(), "passwd")
	_ = os.WriteFile(p, []byte("root:x:0:0::/:/bin/sh\n"), 0o644)
	if identityRows(p)[0] != "root" {
		t.Fatal()
	}
}
