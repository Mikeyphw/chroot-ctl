package controller

import (
	"chrootctl/internal/config"
	sys "chrootctl/internal/system"
	"context"
	"os"
	"path/filepath"
	"strings"
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

func writeCHR08FakeBusybox(t *testing.T, mounts string) string {
	t.Helper()
	bin := filepath.Join(t.TempDir(), "bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	script := `#!/usr/bin/env python3
import os,sys
mounts=os.environ['CHR08_MOUNTS']
log=os.environ.get('CHR08_LOG','')
args=sys.argv[1:]
if log:
    with open(log,'a') as f: f.write(' '.join(args)+'\n')
def rows():
    try:
        with open(mounts) as f: return [x for x in f.read().splitlines() if x.strip()]
    except FileNotFoundError: return []
def put(lines):
    with open(mounts,'w') as f:
        if lines: f.write('\n'.join(lines)+'\n')
if not args: sys.exit(2)
if args[0]=='umount':
    target=args[-1]
    put([x for x in rows() if len(x.split())<2 or x.split()[1]!=target])
    sys.exit(0)
if args[0]!='mount': sys.exit(0)
if any(x.startswith('remount,') for x in args):
    target=args[-1]
    if os.environ.get('CHR08_FAIL_REMOUNT','') and os.environ['CHR08_FAIL_REMOUNT'] in target: sys.exit(7)
    current=[]
    for line in rows():
        f=line.split()
        if len(f)>=4 and f[1]==target and 'bind' in ' '.join(args):
            opts=set(f[3].split(',')); opts.add('ro'); opts.discard('rw'); f[3]=','.join(sorted(opts)); line=' '.join(f)
        current.append(line)
    put(current); sys.exit(0)
if '--bind' in args:
    source,target=args[-2],args[-1]; fstype='none'; opts='rw,bind'
elif '-t' in args:
    i=args.index('-t'); fstype=args[i+1]; source,target=args[-2],args[-1]; opts='rw'
else:
    sys.exit(0)
if os.environ.get('CHR08_FAIL_TARGET','') and os.environ['CHR08_FAIL_TARGET'] in target: sys.exit(9)
put(rows()+[f'{source} {target} {fstype} {opts} 0 0'])
`
	path := filepath.Join(bin, "busybox")
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("CHR08_MOUNTS", mounts)
	return path
}

func TestCHR08MountRejectsDuplicateTargets(t *testing.T) {
	cfg := testCfg(t)
	cfg.ExtraBindMounts = []config.BindMount{{Source: "/tmp", Target: "dev", Enabled: true}}
	c := New(cfg, &sys.Runner{DryRun: true}, nil)
	if _, err := c.mountSpecsValidated(); err == nil {
		t.Fatal("duplicate mount target must be rejected")
	}
}

func TestCHR08MountRollsBackEarlierMountOnFailure(t *testing.T) {
	cfg := testCfg(t)
	cfg.MountDataWithDevSuid = false
	cfg.MediaMounts = nil
	cfg.ExtraBindMounts = nil
	mounts := filepath.Join(t.TempDir(), "mounts")
	if err := os.WriteFile(mounts, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	writeCHR08FakeBusybox(t, mounts)
	t.Setenv("CHR08_FAIL_TARGET", filepath.Join(cfg.ChrootBase(), "sys"))
	c := New(cfg, &sys.Runner{}, nil)
	c.MountsPath = mounts
	result := c.Mount(context.Background())
	if result.Failed == 0 {
		t.Fatalf("expected mount failure: %+v", result)
	}
	data, err := os.ReadFile(mounts)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), filepath.Join(cfg.ChrootBase(), "dev")) {
		t.Fatalf("earlier /dev mount survived rollback: %q", data)
	}
}

func TestCHR08MountRestoresDataFlags(t *testing.T) {
	cfg := testCfg(t)
	cfg.MediaMounts = nil
	cfg.ExtraBindMounts = nil
	cfg.MountDataWithDevSuid = true
	dir := t.TempDir()
	mounts := filepath.Join(dir, "mounts")
	log := filepath.Join(dir, "busybox.log")
	if err := os.WriteFile(mounts, []byte("/dev/block/dm-0 /data ext4 rw,nosuid,nodev,relatime 0 0\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	writeCHR08FakeBusybox(t, mounts)
	t.Setenv("CHR08_LOG", log)
	c := New(cfg, &sys.Runner{}, nil)
	c.MountsPath = mounts
	result := c.Mount(context.Background())
	if result.Failed != 0 {
		t.Fatalf("mount: %+v", result)
	}
	data, err := os.ReadFile(log)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	if !strings.Contains(text, "remount,rw,dev,suid /data") || !strings.Contains(text, "remount,rw,nosuid,nodev /data") {
		t.Fatalf("/data remount/restore missing:\n%s", text)
	}
}

func TestCHR08StatusFailsClosedWhenMountTableUnreadable(t *testing.T) {
	cfg := testCfg(t)
	c := New(cfg, &sys.Runner{DryRun: true}, nil)
	c.MountsPath = filepath.Join(t.TempDir(), "missing")
	if _, err := c.StatusChecked(false); err == nil {
		t.Fatal("missing mount table must fail status")
	}
	if _, err := c.DoctorChecked(); err == nil {
		t.Fatal("missing mount table must fail doctor")
	}
}
