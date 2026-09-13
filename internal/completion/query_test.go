package completion

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeCHR04CompletionConfig(t *testing.T, root string) (string, string) {
	t.Helper()
	chrootRoot := filepath.Join(root, "chroots")
	if err := os.MkdirAll(chrootRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	db := filepath.Join(root, "state", "registry.db")
	cfg := filepath.Join(root, "config.json")
	data := fmt.Sprintf(`{"chroot_root":%q,"database_path":%q,"snapshot_dir":%q,"log_file":%q,"termux_home":%q,"termux_prefix":%q}`,
		chrootRoot, db, filepath.Join(root, "snapshots"), filepath.Join(root, "log.txt"), filepath.Join(root, "home"), filepath.Join(root, "prefix"))
	if err := os.WriteFile(cfg, []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}
	return cfg, db
}

func TestCHR04DynamicCompletionDoesNotCreateRegistryOrState(t *testing.T) {
	root := t.TempDir()
	cfg, db := writeCHR04CompletionConfig(t, root)
	work := filepath.Join(root, "chroots", "work")
	if err := os.MkdirAll(filepath.Join(work, "etc"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(work, "etc", "os-release"), []byte("ID=ubuntu\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	if err := Query(context.Background(), QueryOptions{ConfigPath: cfg, Topic: "chroots"}, &out); err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(out.String()) != "work" {
		t.Fatalf("completion=%q", out.String())
	}
	if _, err := os.Stat(db); !os.IsNotExist(err) {
		t.Fatalf("completion created registry: %v", err)
	}
	if _, err := os.Stat(filepath.Dir(db)); !os.IsNotExist(err) {
		t.Fatalf("completion created state dir: %v", err)
	}
}

func TestCHR04UserCompletionPreservesSelectedName(t *testing.T) {
	root := t.TempDir()
	cfg, _ := writeCHR04CompletionConfig(t, root)
	passwd := filepath.Join(root, "chroots", "work", "etc", "passwd")
	if err := os.MkdirAll(filepath.Dir(passwd), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(passwd, []byte("root:x:0:0:root:/root:/bin/sh\nalice:x:1000:1000::/home/alice:/bin/sh\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	if err := Query(context.Background(), QueryOptions{ConfigPath: cfg, Name: "work", Topic: "users"}, &out); err != nil {
		t.Fatal(err)
	}
	if got := out.String(); !strings.Contains(got, "alice") {
		t.Fatalf("users=%q", got)
	}
}

func TestCHR04GeneratedZshCarriesGlobalCompletionContext(t *testing.T) {
	text, err := GenerateZshFor("chrootctl", "custom")
	if err != nil {
		t.Fatal(err)
	}
	for _, token := range []string{"opt_args[--name]", "opt_args[--config]", "#compdef chrootctl custom", "compdef _chrootctl chrootctl custom"} {
		if !strings.Contains(text, token) {
			t.Fatalf("missing %q", token)
		}
	}
}
