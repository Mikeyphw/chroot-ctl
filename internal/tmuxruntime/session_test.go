package tmuxruntime

import (
	"context"
	"errors"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

type call struct {
	binary    string
	args, env []string
	limit     int
}
type fakeExec struct {
	calls []call
	fn    func([]string) ([]byte, error)
}

func (f *fakeExec) Run(_ context.Context, b string, a, e []string, l int) ([]byte, error) {
	f.calls = append(f.calls, call{b, append([]string(nil), a...), append([]string(nil), e...), l})
	if f.fn != nil {
		return f.fn(a)
	}
	return nil, nil
}
func manager(t *testing.T, f *fakeExec) *SessionManager {
	t.Helper()
	root := t.TempDir()
	p := Paths{Binary: filepath.Join(root, "tmux"), StateRoot: filepath.Join(root, "state"), SocketRoot: filepath.Join(root, "state", "sockets"), Namespace: "chrootctl"}
	return &SessionManager{Paths: p, Exec: f, Timeout: time.Second, ValidateRuntime: func(Paths) error { return nil }}
}
func TestSessionIDDeterministicAndScoped(t *testing.T) {
	a, e := SessionID("androidos", "mike")
	if e != nil {
		t.Fatal(e)
	}
	b, _ := SessionID("androidos", "mike")
	c, _ := SessionID("androidos", "root")
	if a != b || a == c || !strings.HasPrefix(a, ManagedSessionPrefix) {
		t.Fatalf("ids %q %q %q", a, b, c)
	}
}
func TestCreateUsesCentralArgvSafeTmuxInvocation(t *testing.T) {
	f := &fakeExec{}
	m := manager(t, f)
	id, _ := SessionID("androidos", "mike")
	f.fn = func(a []string) ([]byte, error) {
		if has(a, "list-sessions") {
			return []byte(id + "\tandroidos\tmike\t1700000000\t0\t132\t43\n"), nil
		}
		return nil, nil
	}
	s, e := m.Create(context.Background(), CreateRequest{Target: "androidos", Username: "mike", Width: 132, Height: 43, Command: []string{"chroot", "/data/local/a b", "/bin/su", "-", "mike"}, Environment: map[string]string{"TERM": "xterm-256color"}})
	if e != nil {
		t.Fatal(e)
	}
	if s.ID != id {
		t.Fatalf("id=%q", s.ID)
	}
	got := f.calls[0].args
	wantTail := []string{"new-session", "-d", "-s", id, "-x", "132", "-y", "43", "--", "chroot", "/data/local/a b", "/bin/su", "-", "mike"}
	if !reflect.DeepEqual(got[len(got)-len(wantTail):], wantTail) {
		t.Fatalf("argv=%q", got)
	}
	if strings.Contains(strings.Join(got, " "), "sh -c") {
		t.Fatal("tmux invocation introduced shell")
	}
}
func TestListGetCaptureDetachKillResizeAndReconcile(t *testing.T) {
	f := &fakeExec{}
	m := manager(t, f)
	id1, _ := SessionID("a", "u")
	id2, _ := SessionID("b", "u")
	f.fn = func(a []string) ([]byte, error) {
		switch {
		case has(a, "list-sessions"):
			return []byte(id1 + "\ta\tu\t1\t1\t80\t24\n" + id2 + "\tb\tu\t2\t0\t100\t30\nother\tx\tu\t3\t0\t1\t1\n"), nil
		case has(a, "capture-pane"):
			return []byte("hello\n"), nil
		default:
			return nil, nil
		}
	}
	rows, e := m.List(context.Background())
	if e != nil || len(rows) != 2 {
		t.Fatalf("rows=%v err=%v", rows, e)
	}
	g, e := m.Get(context.Background(), id1)
	if e != nil || g == nil || !g.Attached {
		t.Fatalf("get=%v err=%v", g, e)
	}
	out, e := m.Capture(context.Background(), id1, 50)
	if e != nil || out != "hello\n" {
		t.Fatalf("capture=%q %v", out, e)
	}
	if e = m.Detach(context.Background(), id1); e != nil {
		t.Fatal(e)
	}
	if e = m.Resize(context.Background(), id1, 120, 40); e != nil {
		t.Fatal(e)
	}
	r, e := m.Reconcile(context.Background(), map[string]bool{id1: true})
	if e != nil || len(r.Live) != 1 || len(r.Removed) != 1 || r.Removed[0] != id2 {
		t.Fatalf("reconcile=%+v err=%v", r, e)
	}
}
func TestBoundedTimeoutAndStructuredError(t *testing.T) {
	f := &fakeExec{fn: func([]string) ([]byte, error) { return []byte("failure detail"), errors.New("boom") }}
	m := manager(t, f)
	_, e := m.List(context.Background())
	var ce *CommandError
	if !errors.As(e, &ce) || ce.Operation != "list" || !strings.Contains(ce.Output, "failure detail") {
		t.Fatalf("error=%#v", e)
	}
	if m.Timeout <= 0 {
		t.Fatal("timeout not bounded")
	}
}
func TestExplicitEnvironmentDoesNotInheritArbitraryHostValues(t *testing.T) {
	t.Setenv("TOP_SECRET_TEST", "do-not-copy")
	f := &fakeExec{fn: func(a []string) ([]byte, error) {
		if has(a, "list-sessions") {
			return []byte{}, nil
		}
		return nil, nil
	}}
	m := manager(t, f)
	_, _ = m.List(context.Background())
	joined := strings.Join(f.calls[0].env, "\n")
	if strings.Contains(joined, "TOP_SECRET_TEST") || !strings.Contains(joined, "PATH=") {
		t.Fatalf("env=%q", joined)
	}
}
func has(a []string, w string) bool {
	for _, v := range a {
		if v == w {
			return true
		}
	}
	return false
}
