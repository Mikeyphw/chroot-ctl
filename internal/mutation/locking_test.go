package mutation

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestHierarchicalMutationLocks(t *testing.T) {
	dir := t.TempDir()
	l1, _, err := AcquireScope(context.Background(), dir, "target", "alpha", "one")
	if err != nil {
		t.Fatal(err)
	}
	defer l1.Release()
	if l2, _, err := AcquireScope(context.Background(), dir, "target", "alpha", "two"); err == nil {
		_ = l2.Release()
		t.Fatal("same target lock unexpectedly acquired")
	} else {
		var blocked BlockedError
		if !errors.As(err, &blocked) {
			t.Fatalf("wrong error: %v", err)
		}
	}
	l3, _, err := AcquireScope(context.Background(), dir, "target", "beta", "three")
	if err != nil {
		t.Fatalf("independent target should coexist: %v", err)
	}
	defer l3.Release()
	if g, _, err := AcquireScope(context.Background(), dir, "global", "", "global"); err == nil {
		_ = g.Release()
		t.Fatal("global lock acquired while target locks were active")
	}
}

func TestGlobalLockBlocksTargetsAndReleases(t *testing.T) {
	dir := t.TempDir()
	g, _, err := AcquireScope(context.Background(), dir, "global", "", "global")
	if err != nil {
		t.Fatal(err)
	}
	if l, _, err := AcquireScope(context.Background(), dir, "target", "alpha", "target"); err == nil {
		_ = l.Release()
		t.Fatal("target lock acquired under global mutation lock")
	}
	if err := g.Release(); err != nil {
		t.Fatal(err)
	}
	l, _, err := AcquireScope(context.Background(), dir, "target", "alpha", "target")
	if err != nil {
		t.Fatalf("target lock did not recover after global release: %v", err)
	}
	_ = l.Release()
}

func TestHeldContextAvoidsSelfDeadlock(t *testing.T) {
	dir := t.TempDir()
	first, ctx, err := AcquireScope(context.Background(), dir, "target", "alpha", "outer")
	if err != nil {
		t.Fatal(err)
	}
	defer first.Release()
	nested, _, err := AcquireScope(ctx, dir, "target", "alpha", "inner")
	if err != nil {
		t.Fatalf("nested same-context lock should reuse held keys: %v", err)
	}
	if err := nested.Release(); err != nil {
		t.Fatal(err)
	}
}

func TestTargetLockCannotUpgradeSharedGlobalGate(t *testing.T) {
	dir := t.TempDir()
	lease, ctx, err := AcquireScope(context.Background(), dir, "target", "alpha", "outer")
	if err != nil {
		t.Fatal(err)
	}
	defer lease.Release()
	if g, _, err := AcquireScope(ctx, dir, "global", "", "inner"); err == nil {
		_ = g.Release()
		t.Fatal("target-scoped context unexpectedly upgraded shared global gate to exclusive")
	}
}

func TestNestedGlobalExclusiveCanBeReused(t *testing.T) {
	dir := t.TempDir()
	outer, ctx, err := AcquireScope(context.Background(), dir, "global", "", "outer")
	if err != nil {
		t.Fatal(err)
	}
	defer outer.Release()
	inner, _, err := AcquireScope(ctx, dir, "global", "", "inner")
	if err != nil {
		t.Fatalf("nested exclusive global lock should reuse held lock: %v", err)
	}
	if err := inner.Release(); err != nil {
		t.Fatal(err)
	}
}

func TestMutationLockHelper(t *testing.T) {
	if os.Getenv("CHROOTCTL_LOCK_HELPER") != "1" {
		return
	}
	dir, scope, target := os.Getenv("CHROOTCTL_LOCK_DIR"), os.Getenv("CHROOTCTL_LOCK_SCOPE"), os.Getenv("CHROOTCTL_LOCK_TARGET")
	lease, _, err := AcquireScope(context.Background(), dir, scope, target, "helper")
	if err != nil {
		t.Fatal(err)
	}
	defer lease.Release()
	if err := os.WriteFile(os.Getenv("CHROOTCTL_LOCK_READY"), []byte("ready"), 0600); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 500; i++ {
		if _, err := os.Stat(os.Getenv("CHROOTCTL_LOCK_RELEASE")); err == nil {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("helper release timed out")
}

func TestCrossProcessGlobalAndTargetLockInteroperate(t *testing.T) {
	dir := t.TempDir()
	ready := filepath.Join(dir, "ready")
	release := filepath.Join(dir, "release")
	cmd := exec.Command(os.Args[0], "-test.run=^TestMutationLockHelper$", "-test.v")
	cmd.Env = append(os.Environ(), "CHROOTCTL_LOCK_HELPER=1", "CHROOTCTL_LOCK_DIR="+dir, "CHROOTCTL_LOCK_SCOPE=target", "CHROOTCTL_LOCK_TARGET=alpha", "CHROOTCTL_LOCK_READY="+ready, "CHROOTCTL_LOCK_RELEASE="+release)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	waited := false
	defer func() {
		if waited {
			return
		}
		_ = os.WriteFile(release, []byte("x"), 0600)
		_ = cmd.Wait()
	}()
	for i := 0; i < 200; i++ {
		if _, err := os.Stat(ready); err == nil {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if _, err := os.Stat(ready); err != nil {
		t.Fatal("helper never acquired lock")
	}
	if lease, _, err := AcquireScope(context.Background(), dir, "global", "", "parent"); err == nil {
		_ = lease.Release()
		t.Fatal("global lock bypassed cross-process target lock")
	}
	if lease, _, err := AcquireScope(context.Background(), dir, "target", "beta", "parent-beta"); err != nil {
		t.Fatalf("independent target blocked: %v", err)
	} else {
		_ = lease.Release()
	}
	if err := os.WriteFile(release, []byte("x"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := cmd.Wait(); err != nil {
		t.Fatal(err)
	}
	waited = true
}
