package tmuxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	ManagedSessionPrefix  = "cc-"
	defaultCommandTimeout = 5 * time.Second
	maxCaptureBytes       = 1 << 20
)

type Session struct {
	ID, Name, Target, Username string
	Width, Height              int
	CreatedAt                  int64
	Attached                   bool
}
type CreateRequest struct {
	Target, Username string
	Width, Height    int
	Command          []string
	Environment      map[string]string
}
type ReconcileResult struct {
	Live    []Session
	Removed []string
}
type CommandError struct {
	Operation string
	Args      []string
	ExitCode  int
	Output    string
	Err       error
}

func (e *CommandError) Error() string {
	return fmt.Sprintf("tmux %s failed (exit=%d): %s", e.Operation, e.ExitCode, strings.TrimSpace(e.Output))
}
func (e *CommandError) Unwrap() error { return e.Err }

type Executor interface {
	Run(context.Context, string, []string, []string, int) ([]byte, error)
}
type OSExecutor struct{}

func (OSExecutor) Run(ctx context.Context, binary string, args, env []string, limit int) ([]byte, error) {
	cmd := exec.CommandContext(ctx, binary, args...)
	cmd.Env = append([]string(nil), env...)
	var buf bytes.Buffer
	w := &boundedWriter{w: &buf, remaining: limit}
	cmd.Stdout, cmd.Stderr = w, w
	err := cmd.Run()
	return buf.Bytes(), err
}

type boundedWriter struct {
	w         *bytes.Buffer
	remaining int
}

func (w *boundedWriter) Write(p []byte) (int, error) {
	n := len(p)
	if w.remaining <= 0 {
		return n, nil
	}
	part := p
	if len(part) > w.remaining {
		part = part[:w.remaining]
	}
	_, _ = w.w.Write(part)
	w.remaining -= len(part)
	return n, nil
}

type SessionManager struct {
	Paths           Paths
	Exec            Executor
	Timeout         time.Duration
	ValidateRuntime func(Paths) error
}

func NewSessionManager() *SessionManager {
	return &SessionManager{Paths: Resolve(), Exec: OSExecutor{}, Timeout: defaultCommandTimeout}
}
func (m *SessionManager) normalized() (*SessionManager, error) {
	if m == nil {
		return nil, errors.New("tmux session manager is nil")
	}
	cp := *m
	if cp.Exec == nil {
		cp.Exec = OSExecutor{}
	}
	if cp.Timeout <= 0 {
		cp.Timeout = defaultCommandTimeout
	}
	if err := cp.Paths.ValidateAuthority(); err != nil {
		return nil, err
	}
	if err := EnsureState(cp.Paths); err != nil {
		return nil, err
	}
	if cp.ValidateRuntime == nil {
		cp.ValidateRuntime = func(p Paths) error { _, _, err := Validate(p); return err }
	}
	if err := cp.ValidateRuntime(cp.Paths); err != nil {
		return nil, err
	}
	return &cp, nil
}
func deterministicID(target, user string) string {
	h := sha256.Sum256([]byte(target + "\x00" + user))
	return ManagedSessionPrefix + hex.EncodeToString(h[:])[:16]
}
func SessionID(target, user string) (string, error) {
	target, user = strings.TrimSpace(target), strings.TrimSpace(user)
	if target == "" || user == "" {
		return "", errors.New("target and username are required")
	}
	if strings.ContainsAny(target+user, "\x00\r\n") {
		return "", errors.New("target and username must not contain control characters")
	}
	return deterministicID(target, user), nil
}
func (m *SessionManager) socketPath() string {
	return m.Paths.SocketRoot + "/" + m.Paths.Namespace + ".sock"
}
func (m *SessionManager) baseArgs() []string { return []string{"-S", m.socketPath()} }
func (m *SessionManager) env(extra map[string]string) []string {
	values := map[string]string{"HOME": m.Paths.StateRoot, "PATH": "/system/bin:/system/xbin:/vendor/bin:/product/bin", "TMPDIR": m.Paths.StateRoot, "CHROOTCTL_TMUX_NAMESPACE": m.Paths.Namespace}
	for _, k := range []string{"TERM", "LANG", "LC_ALL"} {
		if v := os.Getenv(k); v != "" {
			values[k] = v
		}
	}
	allowed := map[string]bool{"TERM": true, "LANG": true, "LC_ALL": true, "DISPLAY": true, "PULSE_SERVER": true}
	for k, v := range extra {
		if allowed[k] && !strings.ContainsRune(v, '\x00') {
			values[k] = v
		}
	}
	keys := make([]string, 0, len(values))
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make([]string, 0, len(keys))
	for _, k := range keys {
		out = append(out, k+"="+values[k])
	}
	return out
}
func (m *SessionManager) run(ctx context.Context, op string, extraEnv map[string]string, limit int, args ...string) ([]byte, error) {
	mm, err := m.normalized()
	if err != nil {
		return nil, err
	}
	cctx, cancel := context.WithTimeout(ctx, mm.Timeout)
	defer cancel()
	full := append(mm.baseArgs(), args...)
	out, err := mm.Exec.Run(cctx, mm.Paths.Binary, full, mm.env(extraEnv), limit)
	if err == nil {
		return out, nil
	}
	code := -1
	var ee *exec.ExitError
	if errors.As(err, &ee) {
		code = ee.ExitCode()
	}
	if errors.Is(cctx.Err(), context.DeadlineExceeded) {
		return nil, &CommandError{Operation: op, Args: append([]string(nil), full...), ExitCode: code, Output: "command timed out", Err: cctx.Err()}
	}
	return nil, &CommandError{Operation: op, Args: append([]string(nil), full...), ExitCode: code, Output: string(out), Err: err}
}

const sessionFormat = "#{session_name}\t#{@chrootctl_target}\t#{@chrootctl_user}\t#{session_created}\t#{session_attached}\t#{window_width}\t#{window_height}"

func parseSession(line string) (Session, error) {
	f := strings.Split(strings.TrimSpace(line), "\t")
	if len(f) != 7 {
		return Session{}, errors.New("invalid tmux session record")
	}
	if !strings.HasPrefix(f[0], ManagedSessionPrefix) {
		return Session{}, errors.New("unmanaged tmux session")
	}
	created, e := strconv.ParseInt(f[3], 10, 64)
	if e != nil {
		return Session{}, e
	}
	attached, e := strconv.Atoi(f[4])
	if e != nil {
		return Session{}, e
	}
	w, e := strconv.Atoi(f[5])
	if e != nil {
		return Session{}, e
	}
	h, e := strconv.Atoi(f[6])
	if e != nil {
		return Session{}, e
	}
	return Session{ID: f[0], Name: f[0], Target: f[1], Username: f[2], CreatedAt: created, Attached: attached > 0, Width: w, Height: h}, nil
}
func (m *SessionManager) List(ctx context.Context) ([]Session, error) {
	out, err := m.run(ctx, "list", nil, maxCaptureBytes, "list-sessions", "-F", sessionFormat)
	if err != nil {
		var ce *CommandError
		if errors.As(err, &ce) && ce.ExitCode == 1 {
			return []Session{}, nil
		}
		return nil, err
	}
	rows := []Session{}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		s, e := parseSession(line)
		if e == nil {
			rows = append(rows, s)
		}
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].ID < rows[j].ID })
	return rows, nil
}
func (m *SessionManager) Get(ctx context.Context, id string) (*Session, error) {
	if !strings.HasPrefix(id, ManagedSessionPrefix) {
		return nil, errors.New("invalid managed session id")
	}
	rows, e := m.List(ctx)
	if e != nil {
		return nil, e
	}
	for _, s := range rows {
		if s.ID == id {
			x := s
			return &x, nil
		}
	}
	return nil, nil
}
func (m *SessionManager) Create(ctx context.Context, req CreateRequest) (Session, error) {
	id, e := SessionID(req.Target, req.Username)
	if e != nil {
		return Session{}, e
	}
	if len(req.Command) == 0 {
		return Session{}, errors.New("session command argv is required")
	}
	if req.Width <= 0 {
		req.Width = 120
	}
	if req.Height <= 0 {
		req.Height = 40
	}
	args := []string{"new-session", "-d", "-s", id, "-x", strconv.Itoa(req.Width), "-y", strconv.Itoa(req.Height), "--"}
	args = append(args, req.Command...)
	if _, e = m.run(ctx, "create", req.Environment, maxCaptureBytes, args...); e != nil {
		return Session{}, e
	}
	if _, e = m.run(ctx, "metadata-target", nil, maxCaptureBytes, "set-option", "-t", id, "@chrootctl_target", req.Target); e != nil {
		_ = m.Kill(ctx, id)
		return Session{}, e
	}
	if _, e = m.run(ctx, "metadata-user", nil, maxCaptureBytes, "set-option", "-t", id, "@chrootctl_user", req.Username); e != nil {
		_ = m.Kill(ctx, id)
		return Session{}, e
	}
	s, e := m.Get(ctx, id)
	if e != nil {
		return Session{}, e
	}
	if s == nil {
		return Session{}, errors.New("tmux created session but it was not observable")
	}
	s.Target = req.Target
	s.Username = req.Username
	return *s, nil
}
func (m *SessionManager) Detach(ctx context.Context, id string) error {
	if !strings.HasPrefix(id, ManagedSessionPrefix) {
		return errors.New("invalid managed session id")
	}
	_, e := m.run(ctx, "detach", nil, maxCaptureBytes, "detach-client", "-s", id)
	return e
}
func (m *SessionManager) Kill(ctx context.Context, id string) error {
	if !strings.HasPrefix(id, ManagedSessionPrefix) {
		return errors.New("invalid managed session id")
	}
	_, e := m.run(ctx, "kill", nil, maxCaptureBytes, "kill-session", "-t", id)
	return e
}
func (m *SessionManager) Capture(ctx context.Context, id string, lines int) (string, error) {
	if !strings.HasPrefix(id, ManagedSessionPrefix) {
		return "", errors.New("invalid managed session id")
	}
	if lines <= 0 || lines > 5000 {
		lines = 1000
	}
	out, e := m.run(ctx, "capture", nil, maxCaptureBytes, "capture-pane", "-p", "-t", id, "-S", "-"+strconv.Itoa(lines))
	return string(out), e
}
func (m *SessionManager) Resize(ctx context.Context, id string, w, h int) error {
	if !strings.HasPrefix(id, ManagedSessionPrefix) {
		return errors.New("invalid managed session id")
	}
	if w < 20 || h < 5 || w > 1000 || h > 1000 {
		return errors.New("invalid session dimensions")
	}
	_, e := m.run(ctx, "resize", nil, maxCaptureBytes, "resize-window", "-t", id, "-x", strconv.Itoa(w), "-y", strconv.Itoa(h))
	return e
}
func (m *SessionManager) Reconcile(ctx context.Context, expected map[string]bool) (ReconcileResult, error) {
	rows, e := m.List(ctx)
	if e != nil {
		return ReconcileResult{}, e
	}
	r := ReconcileResult{Live: []Session{}, Removed: []string{}}
	for _, s := range rows {
		if expected == nil || expected[s.ID] {
			r.Live = append(r.Live, s)
			continue
		}
		if e := m.Kill(ctx, s.ID); e != nil {
			return r, e
		}
		r.Removed = append(r.Removed, s.ID)
	}
	return r, nil
}
