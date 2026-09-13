package controller

import (
	"chrootctl/internal/config"
	sys "chrootctl/internal/system"
	"context"
	"os"
	"path/filepath"
	"testing"
)

func testCfg(t *testing.T) config.ChrootConfig {
	t.Helper()
	d := t.TempDir()
	c := config.Default(config.RuntimeContext{Home: d})
	c.ChrootRoot = d
	c.DistroName = "ubuntu"
	c.TermuxHome = filepath.Join(d, "termux")
	c.TermuxPrefix = filepath.Join(d, "usr")
	return c
}
func TestMountSpecsAndSessionEnv(t *testing.T) {
	c := New(testCfg(t), &sys.Runner{DryRun: true}, nil)
	s := c.MountSpecs()
	if len(s) < 8 {
		t.Fatalf("mount specs=%d", len(s))
	}
	env := c.SessionEnv(false, true, "alice")
	if env["HOME"] != "/home/alice" || env["DISPLAY"] != ":0" {
		t.Fatalf("env=%v", env)
	}
}
func TestExecInvocationParity(t *testing.T) {
	cfg := testCfg(t)
	_ = os.MkdirAll(filepath.Join(cfg.ChrootBase(), "bin"), 0o755)
	_ = os.WriteFile(filepath.Join(cfg.ChrootBase(), "bin/bash"), []byte("x"), 0o755)
	c := New(cfg, &sys.Runner{DryRun: true}, nil)
	argv, env, err := c.ExecInvocation(false, []string{"echo", "hello world"}, "", false, "alice")
	if err != nil {
		t.Fatal(err)
	}
	if argv[2] != "/bin/su" || env["USER"] != "alice" {
		t.Fatalf("argv=%v env=%v", argv, env)
	}
	root, _, _ := c.ExecInvocation(true, nil, "id", false, "")
	if root[len(root)-2] != "-lc" {
		t.Fatalf("root=%v", root)
	}
}
func TestServiceInvocationUsesLoginShell(t *testing.T) {
	c := New(testCfg(t), &sys.Runner{DryRun: true}, nil)
	argv, _, err := c.ServiceInvocation(false, "code-server", true, "mike")
	if err != nil {
		t.Fatal(err)
	}
	if argv[2] != "/bin/su" || argv[5] != "-c" {
		t.Fatalf("argv=%v", argv)
	}
}

func TestGateADryRunMountDoesNotCreateFilesystemState(t *testing.T) {
	cfg := testCfg(t)
	root := cfg.ChrootBase()
	mounts := filepath.Join(t.TempDir(), "mounts")
	if err := os.WriteFile(mounts, nil, 0600); err != nil {
		t.Fatal(err)
	}
	c := New(cfg, &sys.Runner{DryRun: true}, nil)
	c.MountsPath = mounts
	result := c.Mount(context.Background())
	if result.Failed != 0 {
		t.Fatalf("dry-run mount failed: %+v", result)
	}
	if _, err := os.Lstat(root); !os.IsNotExist(err) {
		t.Fatalf("dry-run mount created chroot root %s (err=%v)", root, err)
	}
}
