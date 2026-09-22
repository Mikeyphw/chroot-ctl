package clipboard

import (
	"context"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"chrootctl/internal/config"
	sys "chrootctl/internal/system"
)

func chr14TempRoot(t *testing.T) string {
	t.Helper()
	// Unix-domain socket paths are limited to roughly 108 bytes on Linux/Android.
	// Devtool artifact validation may place TMPDIR below a long transaction path,
	// so walk toward a shorter writable ancestor (preferring $PREFIX/tmp on Termux)
	// until the generated clipboard socket remains safely below that limit.
	candidates := make([]string, 0, 8)
	if prefix := strings.TrimSpace(os.Getenv("PREFIX")); prefix != "" {
		candidates = append(candidates, filepath.Join(prefix, "tmp"))
	}
	for cur := filepath.Clean(os.TempDir()); ; cur = filepath.Dir(cur) {
		candidates = append(candidates, cur)
		parent := filepath.Dir(cur)
		if parent == cur {
			break
		}
	}
	seen := map[string]bool{}
	for _, base := range candidates {
		base = filepath.Clean(base)
		if seen[base] {
			continue
		}
		seen[base] = true
		projected := filepath.Join(base, "c14-xxxxxxxxxx", "usr", "tmp", "chrootctl", "clipboard.sock")
		if len(projected) >= 104 {
			continue
		}
		root, err := os.MkdirTemp(base, "c14-")
		if err == nil {
			t.Cleanup(func() { _ = os.RemoveAll(root) })
			return root
		}
	}
	t.Fatalf("no writable temporary root with a Unix-socket-safe path (TMPDIR=%q)", os.TempDir())
	return ""
}

func chr14Config(t *testing.T) config.ChrootConfig {
	t.Helper()
	root := chr14TempRoot(t)
	cfg := config.Default(config.RuntimeContext{Home: root})
	cfg.ChrootRoot = filepath.Join(root, "chroots")
	cfg.DistroName = "work"
	cfg.TermuxHome = filepath.Join(root, "home")
	cfg.TermuxPrefix = filepath.Join(root, "usr")
	if err := os.MkdirAll(cfg.TermuxHome, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(cfg.TermuxPrefix, "tmp"), 0o700); err != nil {
		t.Fatal(err)
	}
	return cfg
}

func TestCHR14DefaultPathsSharePrivateTermuxControlRoot(t *testing.T) {
	cfg := chr14Config(t)
	paths := DefaultPaths(cfg)
	wantRoot := filepath.Join(cfg.TermuxPrefix, "tmp", "chrootctl")
	for _, p := range []string{paths.SocketPath, paths.PIDFile, paths.LogFile, tokenPath(paths.SocketPath), lockPath(paths.SocketPath)} {
		if !strings.HasPrefix(filepath.Clean(p), wantRoot+string(filepath.Separator)) && filepath.Clean(p) != wantRoot {
			t.Fatalf("%s is outside %s", p, wantRoot)
		}
	}
}

func TestCHR14CustomControlParentMustAlreadyBePrivate(t *testing.T) {
	cfg := chr14Config(t)
	pubRoot, err := os.MkdirTemp("", "c14pub-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(pubRoot) })
	pub := filepath.Join(pubRoot, "public")
	if err := os.MkdirAll(pub, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(pub, 0o755); err != nil {
		t.Fatal(err)
	}
	if info, err := os.Stat(pub); err != nil {
		t.Fatal(err)
	} else if info.Mode().Perm()&0o077 == 0 {
		t.Skip("filesystem did not preserve public directory mode")
	}
	_, err = normalizePaths(cfg, Paths{SocketPath: filepath.Join(pub, "clipboard.sock")})
	if err == nil || !strings.Contains(err.Error(), "not private") {
		t.Fatalf("expected private parent rejection, got %v", err)
	}
	missing := filepath.Join(t.TempDir(), "missing", "clipboard.sock")
	_, err = normalizePaths(cfg, Paths{SocketPath: missing})
	if err == nil || !strings.Contains(err.Error(), "must already exist") {
		t.Fatalf("expected missing custom parent rejection, got %v", err)
	}
}

func TestCHR14RunDaemonRefusesExistingSocket(t *testing.T) {
	cfg := chr14Config(t)
	paths, err := normalizePaths(cfg, Paths{})
	if err != nil {
		t.Fatal(err)
	}
	if err = atomicPrivate(tokenPath(paths.SocketPath), strings.Repeat("a", 64), 0o600); err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("unix", paths.SocketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	err = RunDaemon(context.Background(), cfg, &sys.Runner{}, paths)
	if err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatalf("expected existing socket rejection, got %v", err)
	}
}

func installMarkedWrappers(t *testing.T, cfg config.ChrootConfig, target string) {
	t.Helper()
	bin := filepath.Join(cfg.ChrootRoot, target, "usr", "local", "bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"termux-clip", "chrootctl-xsel", "chrootctl-xclip"} {
		body := "#!/bin/sh\n# " + WrapperMarkerVersion + " " + name + "\n"
		if err := os.WriteFile(filepath.Join(bin, name), []byte(body), 0o755); err != nil {
			t.Fatal(err)
		}
	}
}

func TestCHR14TargetAuthorizationRequiresMarkedWrappers(t *testing.T) {
	cfg := chr14Config(t)
	if resp := handleRequest(context.Background(), cfg, &sys.Runner{}, Request{Action: "ping", Target: "../bad"}); resp.OK || !strings.Contains(resp.Error, "invalid clipboard target") {
		t.Fatalf("expected invalid target rejection: %#v", resp)
	}
	if resp := handleRequest(context.Background(), cfg, &sys.Runner{}, Request{Action: "ping", Target: "work"}); resp.OK || !strings.Contains(resp.Error, "not enabled") {
		t.Fatalf("expected not-enabled target rejection: %#v", resp)
	}
	installMarkedWrappers(t, cfg, "work")
	if resp := handleRequest(context.Background(), cfg, &sys.Runner{}, Request{Action: "ping", Target: "work"}); !resp.OK || !resp.Ready {
		t.Fatalf("expected enabled target ping: %#v", resp)
	}
}

func TestCHR14DoctorReportsSelectedTargetEnablement(t *testing.T) {
	cfg := chr14Config(t)
	installMarkedWrappers(t, cfg, "work")
	paths := DefaultPaths(cfg)
	doc := Doctor(cfg, paths)
	if doc["target"] != "work" || doc["target_enabled"] != true || doc["wrappers_ready"] != true {
		t.Fatalf("unexpected doctor payload: %#v", doc)
	}
}
