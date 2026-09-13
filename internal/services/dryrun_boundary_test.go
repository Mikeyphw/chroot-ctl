package services

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"chrootctl/internal/registry"
)

func TestDryRunContainerConstructionIsZeroWrite(t *testing.T) {
	root := t.TempDir()
	cfgPath := filepath.Join(root, "config.json")
	dbPath := filepath.Join(root, "state", "registry.sqlite3")
	logPath := filepath.Join(root, "logs", "chrootctl.log")
	chrootRoot := filepath.Join(root, "chroots")
	body := fmt.Sprintf(`{"username":"mike","chroot_root":%q,"database_path":%q,"log_file":%q,"snapshot_dir":%q,"service_state_dir":%q,"service_log_dir":%q,"service_dirs":[%q]}`,
		chrootRoot, dbPath, logPath, filepath.Join(root, "snapshots"), filepath.Join(root, "run", "services"), filepath.Join(root, "service-logs"), filepath.Join(root, "services"))
	if err := os.WriteFile(cfgPath, []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := New(cfgPath, true, false)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	for _, path := range []string{dbPath, logPath, filepath.Join(filepath.Dir(dbPath), "operations"), chrootRoot, filepath.Join(root, "snapshots")} {
		if _, err := os.Lstat(path); !os.IsNotExist(err) {
			t.Fatalf("dry-run created %s (err=%v)", path, err)
		}
	}
	err = c.Registry.Upsert(context.Background(), registry.ChrootInput{Name: "should-not-write", Distro: "ubuntu", Path: filepath.Join(chrootRoot, "should-not-write")})
	if err == nil {
		t.Fatal("dry-run registry accepted a write")
	}
}
