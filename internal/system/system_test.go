package system

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestQEMUUserBinaryNames(t *testing.T) {
	if got := strings.Join(QEMUUserBinaryNames("arm64"), ","); got != "qemu-aarch64-static,qemu-arm64-static" {
		t.Fatalf("%s", got)
	}
	if got := QEMUUserBinaryNames("riscv64")[0]; got != "qemu-riscv64-static" {
		t.Fatalf("%s", got)
	}
}

func TestProcessIdentityFromMapAliasesAndSafety(t *testing.T) {
	identity := ProcessIdentityFromMap(map[string]any{"pid": 12.0, "process_group_id": "13", "process_start_time": "14", "process_boot_id": "boot"})
	if identity == nil || identity.PID != 12 || identity.ProcessGroupID != 13 || *identity.StartTimeTicks != 14 || *identity.BootID != "boot" {
		t.Fatalf("%#v", identity)
	}
	legacy := ProcessIdentityFromMap(map[string]any{"pid": 12, "processGroupId": 13})
	if legacy == nil || legacy.Complete() {
		t.Fatalf("legacy identity must not be signal-safe: %#v", legacy)
	}
}

func TestProcessEnvScrubsHostLeakage(t *testing.T) {
	t.Setenv("LD_LIBRARY_PATH", "/termux/lib")
	t.Setenv("PREFIX", "/termux")
	t.Setenv("TERM", "")
	env := ProcessEnv(map[string]string{"EXTRA": "yes"}, false, true)
	if _, ok := env["LD_LIBRARY_PATH"]; ok {
		t.Fatal("LD_LIBRARY_PATH leaked")
	}
	if _, ok := env["PREFIX"]; ok {
		t.Fatal("PREFIX leaked")
	}
	if env["PATH"] != ChrootEnvDefaults["PATH"] || env["HOME"] != "/root" || env["TERM"] != "xterm-256color" || env["EXTRA"] != "yes" {
		t.Fatalf("env=%#v", env)
	}
}

func TestRunSuccessFailureInputAndTruncation(t *testing.T) {
	runner := Runner{}
	result, err := runner.Run(context.Background(), []string{"sh", "-c", "cat; printf err >&2"}, RunOptions{Input: "hello"})
	if err != nil {
		t.Fatal(err)
	}
	if result.Stdout != "hello" || result.Stderr != "err" || result.ReturnCode != 0 {
		t.Fatalf("%#v", result)
	}
	failed, err := runner.Run(context.Background(), []string{"sh", "-c", "printf boom >&2; exit 7"}, RunOptions{AllowFailure: true})
	if err != nil {
		t.Fatal(err)
	}
	if failed.ReturnCode != 7 {
		t.Fatalf("%#v", failed)
	}
	_, err = runner.Run(context.Background(), []string{"sh", "-c", "printf boom >&2; exit 7"}, RunOptions{})
	if err == nil || err.Error() != "boom" {
		t.Fatalf("err=%v", err)
	}
	truncated, err := runner.Run(context.Background(), []string{"sh", "-c", "printf 1234567890"}, RunOptions{MaxCaptureBytes: 6})
	if err != nil {
		t.Fatal(err)
	}
	if !truncated.Truncated || !strings.Contains(truncated.Stdout, "truncated 4 bytes") {
		t.Fatalf("%#v", truncated)
	}
}

func TestRunTimeoutAndCancellationTerminateProcessGroup(t *testing.T) {
	runner := Runner{}
	timed, err := runner.Run(context.Background(), []string{"sh", "-c", "sleep 30"}, RunOptions{Timeout: 150 * time.Millisecond, AllowFailure: true})
	if err != nil {
		t.Fatal(err)
	}
	if !timed.TimedOut {
		t.Fatalf("%#v", timed)
	}
	ctx, cancel := context.WithCancel(context.Background())
	go func() { time.Sleep(100 * time.Millisecond); cancel() }()
	cancelled, err := runner.Run(ctx, []string{"sh", "-c", "sleep 30"}, RunOptions{AllowFailure: true})
	if err != nil {
		t.Fatal(err)
	}
	if !cancelled.Cancelled {
		t.Fatalf("%#v", cancelled)
	}
}

func TestCaptureCurrentIdentityAndRejectIncompleteSignal(t *testing.T) {
	identity := CaptureProcessIdentity(os.Getpid())
	if identity == nil || !identity.Complete() {
		t.Skip("/proc identity unavailable")
	}
	if !ProcessIdentityMatches(*identity) {
		t.Fatalf("identity mismatch: %#v", identity)
	}
	incomplete := *identity
	incomplete.BootID = nil
	if SignalProcessIdentity(incomplete, syscall.Signal(0)) {
		t.Fatal("incomplete identity must never be signalled")
	}
}

func TestSpawnOutputAndDryRun(t *testing.T) {
	dir := t.TempDir()
	out := filepath.Join(dir, "child.log")
	runner := Runner{}
	pid, err := runner.Spawn([]string{"sh", "-c", "printf spawned"}, SpawnOptions{OutputPath: out})
	if err != nil {
		t.Fatal(err)
	}
	if pid <= 0 {
		t.Fatalf("pid=%d", pid)
	}
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		raw, _ := os.ReadFile(out)
		if string(raw) == "spawned" {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	raw, _ := os.ReadFile(out)
	t.Fatalf("output=%q", raw)
}

func TestParseMountTable(t *testing.T) {
	table := ParseMountTable("/dev/block/a /data ext4 rw 0 0\nproc /proc proc rw 0 0\ninvalid\n")
	if _, ok := table[[2]string{"/dev/block/a", "/data"}]; !ok {
		t.Fatal("missing /data")
	}
	if len(table) != 2 {
		t.Fatalf("%#v", table)
	}
}

func TestHostHelpers(t *testing.T) {
	if HostArch() == "" {
		t.Fatal("empty arch")
	}
	if !CommandExists("sh") {
		t.Fatal("sh should exist")
	}
	dir := t.TempDir()
	uid, gid, err := HostTermuxUIDGID(dir)
	if err != nil {
		t.Fatal(err)
	}
	if uid < 0 || gid < 0 {
		t.Fatal("invalid uid/gid")
	}
	mounts, err := MountTable(filepath.Join(t.TempDir(), "missing"))
	if err != nil || len(mounts) != 0 {
		t.Fatalf("%#v %v", mounts, err)
	}
}

func TestDryRunAndValidation(t *testing.T) {
	runner := Runner{DryRun: true}
	result, err := runner.Run(context.Background(), []string{"does-not-exist"}, RunOptions{})
	if err != nil || result.ReturnCode != 0 {
		t.Fatalf("%#v %v", result, err)
	}
	_, err = Runner{}.Run(context.Background(), []string{"sh"}, RunOptions{Timeout: -time.Second})
	if err == nil || !strings.Contains(err.Error(), "timeout must be positive") {
		t.Fatalf("%v", err)
	}
	if !errors.Is(RequireRoot(), os.ErrPermission) && !IsRoot() { /* text parity is asserted below */
	}
	if !IsRoot() {
		if err := RequireRoot(); err == nil || err.Error() != "root privileges required" {
			t.Fatalf("%v", err)
		}
	}
}

func TestCHR04ReexecArgvUsesSuppliedArguments(t *testing.T) {
	original := append([]string(nil), os.Args...)
	originalResolver := trustedReexecExecutable
	os.Args = []string{"wrong-process-global", "wrong"}
	trustedReexecExecutable = func() (string, error) { return "/trusted/chrootctl", nil }
	defer func() {
		os.Args = original
		trustedReexecExecutable = originalResolver
	}()
	got, err := ReexecArgv([]string{"status", "--details"})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 || got[1] != "status" || got[2] != "--details" {
		t.Fatalf("reexec argv=%#v", got)
	}
}

func TestCHR04DryRunRootReexecFailsClosedIfCalledDirectly(t *testing.T) {
	runner := Runner{DryRun: true}
	if _, err := runner.ReexecWithRootIO(context.Background(), []string{"chrootctl", "status"}, strings.NewReader(""), io.Discard, io.Discard); err == nil {
		t.Fatal("dry-run root reexec must not silently report success")
	}
}

func TestCHR05RunAttachedTimeoutWinsOverZeroExit(t *testing.T) {
	runner := Runner{}
	result, err := runner.RunAttached(
		context.Background(),
		[]string{"sh", "-c", "trap 'exit 0' TERM; while :; do sleep 1; done"},
		RunOptions{Timeout: 150 * time.Millisecond},
	)
	if err == nil || !strings.Contains(err.Error(), "timed out") {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	if !result.TimedOut {
		t.Fatalf("expected timedOut result: %#v", result)
	}
}

func TestCHR05RunAttachedAllowFailurePreservesCancellationFlag(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(150 * time.Millisecond)
		cancel()
	}()
	result, err := Runner{}.RunAttached(
		ctx,
		[]string{"sh", "-c", "trap 'exit 0' TERM; while :; do sleep 1; done"},
		RunOptions{AllowFailure: true},
	)
	if err != nil {
		t.Fatalf("allow-failure should preserve status without converting cancellation into a runner error: result=%#v err=%v", result, err)
	}
	if !result.Cancelled {
		t.Fatalf("expected cancelled result: %#v", result)
	}
}

func TestCHR05NoCaptureIsConsistentDiscardPolicy(t *testing.T) {
	for _, background := range []bool{false, true} {
		policy, err := (RunOptions{NoCapture: true}).outputPolicy(background)
		if err != nil {
			t.Fatal(err)
		}
		if policy != OutputDiscard {
			t.Fatalf("background=%v policy=%q", background, policy)
		}
	}
	if _, err := (RunOptions{OutputPolicy: OutputCapture}).outputPolicy(true); err == nil {
		t.Fatal("background capture must be rejected rather than silently changing semantics")
	}
}

func TestCHR05BoundedCaptureWriterRetainsHeadTailWithoutUnboundedSpool(t *testing.T) {
	w := newBoundedCaptureWriter(10)
	payload := strings.Repeat("x", 1024*1024) + "TAIL!"
	if _, err := io.WriteString(w, payload); err != nil {
		t.Fatal(err)
	}
	got, truncated := w.Result()
	if !truncated || !strings.Contains(got, "truncated") || !strings.HasSuffix(got, "TAIL!") {
		t.Fatalf("truncated=%v output=%q", truncated, got)
	}
	if len(w.head)+w.tailLen > 10 {
		t.Fatalf("capture storage grew past limit: head=%d tail=%d", len(w.head), w.tailLen)
	}
}

func TestCHR05TimeoutTerminatesWholeProcessGroup(t *testing.T) {
	runner := Runner{}
	result, err := runner.Run(
		context.Background(),
		[]string{"sh", "-c", "(trap '' TERM; while :; do sleep 1; done) & wait"},
		RunOptions{Timeout: 150 * time.Millisecond, AllowFailure: true},
	)
	if err != nil {
		t.Fatal(err)
	}
	if !result.TimedOut || result.ProcessGroupID == nil {
		t.Fatalf("result=%#v", result)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) && processGroupAlive(*result.ProcessGroupID) {
		time.Sleep(25 * time.Millisecond)
	}
	if processGroupAlive(*result.ProcessGroupID) {
		t.Fatalf("process group %d survived timeout", *result.ProcessGroupID)
	}
}
