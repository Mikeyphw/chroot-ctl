package clipboard

import (
	"chrootctl/internal/config"
	"os"
	"path/filepath"
	"testing"
)

func TestPathsTokenAndStatus(t *testing.T) {
	cfg := config.Default(config.RuntimeContext{Home: t.TempDir()})
	p := DefaultPaths(cfg)
	if p.PIDFile == "" || p.SocketPath == "" {
		t.Fatal(p)
	}
	a, _ := newToken()
	b, _ := newToken()
	if len(a) != 64 || a == b || !equal(a, a) || equal(a, b) {
		t.Fatal("token")
	}
	s := DaemonStatus(t.TempDir() + "/none")
	if s["running"].(bool) {
		t.Fatal(s)
	}
}

func TestCHR08ClipboardDoctorRequiresGeneratedWrapperProvenance(t *testing.T) {
	root := t.TempDir()
	cfg := config.Default(config.RuntimeContext{Home: root})
	cfg.ChrootRoot = filepath.Join(root, "chroots")
	cfg.DistroName = "work"
	cfg.TermuxPrefix = filepath.Join(root, "usr")
	bin := filepath.Join(cfg.ChrootBase(), "usr/local/bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"termux-clip", "chrootctl-xsel", "chrootctl-xclip"} {
		body := "#!/bin/sh\n# chrootctl-clipboard-wrapper:v1 " + name + "\n"
		if err := os.WriteFile(filepath.Join(bin, name), []byte(body), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	doc := Doctor(cfg, Paths{SocketPath: filepath.Join(root, "none.sock"), PIDFile: filepath.Join(root, "none.pid")})
	if ready, _ := doc["wrappers_ready"].(bool); !ready {
		t.Fatalf("generated wrappers should be ready: %#v", doc)
	}
	if err := os.WriteFile(filepath.Join(bin, "chrootctl-xsel"), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	doc = Doctor(cfg, Paths{SocketPath: filepath.Join(root, "none.sock"), PIDFile: filepath.Join(root, "none.pid")})
	if ready, _ := doc["wrappers_ready"].(bool); ready {
		t.Fatal("unmarked wrapper must not be reported ready")
	}
}
