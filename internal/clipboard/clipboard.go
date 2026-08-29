package clipboard

import (
	"bufio"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"chrootctl/internal/config"
	sys "chrootctl/internal/system"
)

const (
	ChrootSocket          = "/tmp/chrootctl/clipboard.sock"
	MaxClipboardTextBytes = 1024 * 1024
	MaxClipboardWireBytes = 2 * 1024 * 1024
)

type Paths struct {
	SocketPath string `json:"socket_path"`
	PIDFile    string `json:"pid_file"`
	LogFile    string `json:"log_file"`
}

type Request struct {
	Action string `json:"action"`
	Text   string `json:"text,omitempty"`
	Token  string `json:"token"`
}
type Response struct {
	OK    bool   `json:"ok"`
	Ready bool   `json:"ready,omitempty"`
	Text  string `json:"text,omitempty"`
	Error string `json:"error,omitempty"`
}

func DefaultPaths(cfg config.ChrootConfig) Paths {
	runtimeDir := filepath.Join(cfg.TermuxPrefix, "tmp", "chrootctl")
	return Paths{
		SocketPath: filepath.Join(runtimeDir, "clipboard.sock"),
		PIDFile:    filepath.Join(config.AndroidStateRoot, "clipboard-daemon.pid"),
		LogFile:    filepath.Join(config.AndroidStateRoot, "clipboard-daemon.log"),
	}
}
func tokenPath(socket string) string { return filepath.Join(filepath.Dir(socket), "clipboard.token") }
func identityPath(pid string) string { return pid + ".identity.json" }

func safeParent(path string, mode os.FileMode) error {
	parent := filepath.Dir(path)
	if err := os.MkdirAll(parent, mode); err != nil {
		return err
	}
	info, err := os.Lstat(parent)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return fmt.Errorf("unsafe clipboard control directory: %s", parent)
	}
	_ = os.Chmod(parent, mode)
	if info, err := os.Lstat(path); err == nil && info.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("refusing clipboard symlink path: %s", path)
	}
	return nil
}
func atomicPrivate(path, text string, mode os.FileMode) error {
	if err := safeParent(path, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	_ = tmp.Chmod(mode)
	if _, err = tmp.WriteString(text); err != nil {
		return err
	}
	if err = tmp.Sync(); err != nil {
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	if err = os.Rename(name, path); err != nil {
		return err
	}
	return os.Chmod(path, mode)
}
func newToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}
func equal(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

func readPID(path string) *int {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || pid <= 0 {
		return nil
	}
	return &pid
}
func readIdentity(path string) *sys.ProcessIdentity {
	data, err := os.ReadFile(identityPath(path))
	if err != nil {
		return nil
	}
	var raw map[string]any
	if json.Unmarshal(data, &raw) != nil {
		return nil
	}
	return sys.ProcessIdentityFromMap(raw)
}
func DaemonStatus(pidFile string) map[string]any {
	pid := readPID(pidFile)
	identity := readIdentity(pidFile)
	running := pid != nil && identity != nil && identity.PID == *pid && sys.ProcessIdentityMatches(*identity)
	var value any = nil
	if pid != nil {
		value = *pid
	}
	return map[string]any{"running": running, "pid": value, "identity_verified": running}
}

func hostEnv(cfg config.ChrootConfig) map[string]string {
	return map[string]string{"HOME": cfg.TermuxHome, "PREFIX": cfg.TermuxPrefix, "TMPDIR": filepath.Join(cfg.TermuxPrefix, "tmp"), "PATH": filepath.Join(cfg.TermuxPrefix, "bin") + ":/system/bin:/system/xbin:/vendor/bin", "LD_LIBRARY_PATH": filepath.Join(cfg.TermuxPrefix, "lib")}
}

func StartDaemon(ctx context.Context, cfg config.ChrootConfig, runner *sys.Runner, paths Paths) (map[string]any, error) {
	if runner == nil {
		return nil, errors.New("runner is nil")
	}
	if paths.SocketPath == "" {
		paths = DefaultPaths(cfg)
	}
	status := DaemonStatus(paths.PIDFile)
	if status["running"] == true {
		if r, err := socketRequest(ctx, paths.SocketPath, Request{Action: "ping"}, ""); err == nil && r.OK && r.Ready {
			return map[string]any{"started": false, "running": true, "pid": status["pid"], "socket": paths.SocketPath, "log_file": paths.LogFile}, nil
		}
		identity := readIdentity(paths.PIDFile)
		if identity == nil || !sys.ProcessIdentityMatches(*identity) {
			return nil, errors.New("clipboard daemon control state changed during restart")
		}
		sys.TerminateProcessIdentity(*identity, 2*time.Second)
		if sys.ProcessIdentityMatches(*identity) {
			return nil, errors.New("verified clipboard daemon could not be terminated; refusing to start a duplicate")
		}
		_ = os.Remove(paths.PIDFile)
		_ = os.Remove(identityPath(paths.PIDFile))
		_ = os.Remove(paths.SocketPath)
	}
	uid, gid, err := sys.HostTermuxUIDGID(cfg.TermuxHome)
	if err != nil {
		return nil, err
	}
	for _, p := range []string{paths.PIDFile, paths.LogFile, identityPath(paths.PIDFile), paths.SocketPath} {
		if err = safeParent(p, 0o700); err != nil {
			return nil, err
		}
	}
	runtimeDir := filepath.Dir(paths.SocketPath)
	if os.Geteuid() == 0 {
		if err = os.Chown(runtimeDir, uid, gid); err != nil {
			return nil, fmt.Errorf("cannot secure clipboard runtime directory %s: %w", runtimeDir, err)
		}
	}
	_ = os.Chmod(runtimeDir, 0o700)
	_ = os.Remove(paths.PIDFile)
	_ = os.Remove(identityPath(paths.PIDFile))
	token, err := newToken()
	if err != nil {
		return nil, err
	}
	tp := tokenPath(paths.SocketPath)
	if err = atomicPrivate(tp, token, 0o600); err != nil {
		return nil, err
	}
	if os.Geteuid() == 0 {
		_ = os.Chown(tp, uid, gid)
	}
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	pid, err := runner.Spawn([]string{exe, "clipboard", "daemon", "run", "--socket", paths.SocketPath, "--pid-file", paths.PIDFile}, sys.SpawnOptions{Env: hostEnv(cfg), OutputPath: paths.LogFile, Append: true, UID: &uid, GID: &gid})
	if err != nil {
		return nil, err
	}
	identity := sys.CaptureProcessIdentity(pid)
	if identity == nil || identity.StartTimeTicks == nil || identity.BootID == nil {
		if identity != nil {
			sys.TerminateProcessIdentity(*identity, 2*time.Second)
		}
		return nil, errors.New("clipboard daemon started without a verifiable process identity")
	}
	if err = atomicPrivate(paths.PIDFile, fmt.Sprintf("%d\n", pid), 0o600); err != nil {
		return nil, err
	}
	raw, _ := json.Marshal(identity)
	if err = atomicPrivate(identityPath(paths.PIDFile), string(raw)+"\n", 0o600); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if !sys.ProcessIdentityMatches(*identity) {
			break
		}
		if _, e := os.Stat(paths.SocketPath); e == nil {
			if r, e := socketRequest(ctx, paths.SocketPath, Request{Action: "ping"}, token); e == nil && r.OK && r.Ready {
				return map[string]any{"started": true, "running": true, "pid": pid, "socket": paths.SocketPath, "log_file": paths.LogFile, "uid": uid, "gid": gid}, nil
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	sys.TerminateProcessIdentity(*identity, 2*time.Second)
	_ = os.Remove(paths.PIDFile)
	_ = os.Remove(identityPath(paths.PIDFile))
	_ = os.Remove(paths.SocketPath)
	return nil, errors.New("clipboard daemon did not become ready within 5 seconds")
}
func StopDaemon(pidFile string) map[string]any {
	pid := readPID(pidFile)
	identity := readIdentity(pidFile)
	if pid == nil || identity == nil || identity.PID != *pid || !sys.ProcessIdentityMatches(*identity) {
		_ = os.Remove(pidFile)
		_ = os.Remove(identityPath(pidFile))
		var v any = nil
		if pid != nil {
			v = *pid
		}
		return map[string]any{"stopped": false, "running": false, "pid": v, "identity_verified": false}
	}
	stopped := sys.TerminateProcessIdentity(*identity, 2*time.Second)
	running := sys.ProcessIdentityMatches(*identity)
	if !running {
		_ = os.Remove(pidFile)
		_ = os.Remove(identityPath(pidFile))
	}
	return map[string]any{"stopped": stopped && !running, "running": running, "pid": *pid, "identity_verified": true}
}

func RunDaemon(ctx context.Context, cfg config.ChrootConfig, runner *sys.Runner, paths Paths) error {
	if paths.SocketPath == "" {
		paths = DefaultPaths(cfg)
	}
	if err := safeParent(paths.SocketPath, 0o700); err != nil {
		return err
	}
	tp := tokenPath(paths.SocketPath)
	if err := safeParent(tp, 0o700); err != nil {
		return err
	}
	data, err := os.ReadFile(tp)
	if err != nil {
		return err
	}
	token := strings.TrimSpace(string(data))
	if len(token) < 32 {
		return errors.New("clipboard authentication token is missing or invalid")
	}
	if info, err := os.Lstat(paths.SocketPath); err == nil {
		if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 {
			return fmt.Errorf("refusing non-socket clipboard path: %s", paths.SocketPath)
		}
		_ = os.Remove(paths.SocketPath)
	}
	uid, _, err := sys.HostTermuxUIDGID(cfg.TermuxHome)
	if err != nil {
		return err
	}
	ln, err := net.Listen("unix", paths.SocketPath)
	if err != nil {
		return err
	}
	defer ln.Close()
	defer os.Remove(paths.SocketPath)
	_ = os.Chmod(paths.SocketPath, 0o600)
	u := ln.(*net.UnixListener)
	for {
		_ = u.SetDeadline(time.Now().Add(time.Second))
		conn, err := u.AcceptUnix()
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				select {
				case <-ctx.Done():
					return nil
				default:
					continue
				}
			}
			return err
		}
		go serve(conn, cfg, runner, token, uid)
	}
}
func peerUID(conn *net.UnixConn) (int, error) {
	raw, err := conn.SyscallConn()
	if err != nil {
		return 0, err
	}
	uid := -1
	var inner error
	err = raw.Control(func(fd uintptr) {
		cred, e := syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
		if e != nil {
			inner = e
			return
		}
		uid = int(cred.Uid)
	})
	if err != nil {
		return 0, err
	}
	if inner != nil {
		return 0, inner
	}
	if uid < 0 {
		return 0, errors.New("SO_PEERCRED is required for clipboard peer authentication")
	}
	return uid, nil
}
func serve(conn *net.UnixConn, cfg config.ChrootConfig, runner *sys.Runner, token string, termuxUID int) {
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	uid, err := peerUID(conn)
	resp := Response{}
	if err != nil {
		resp.Error = err.Error()
	} else if uid != 0 && uid != termuxUID {
		resp.Error = fmt.Sprintf("clipboard peer uid %d is not authorized", uid)
	} else {
		var req Request
		err = decodeLimited(conn, &req)
		if err != nil {
			resp.Error = err.Error()
		} else if !equal(req.Token, token) {
			resp.Error = "clipboard authentication failed"
		} else {
			resp = handleRequest(context.Background(), cfg, runner, req)
		}
	}
	_ = json.NewEncoder(conn).Encode(resp)
}
func decodeLimited(conn net.Conn, out any) error {
	reader := bufio.NewReader(&ioLimit{R: conn, N: MaxClipboardWireBytes})
	dec := json.NewDecoder(reader)
	if err := dec.Decode(out); err != nil {
		return err
	}
	return nil
}

type ioLimit struct {
	R net.Conn
	N int
}

func (l *ioLimit) Read(p []byte) (int, error) {
	if l.N <= 0 {
		return 0, errors.New("clipboard request exceeds wire limit")
	}
	if len(p) > l.N {
		p = p[:l.N]
	}
	n, e := l.R.Read(p)
	l.N -= n
	return n, e
}
func handleRequest(ctx context.Context, cfg config.ChrootConfig, runner *sys.Runner, req Request) Response {
	switch strings.ToLower(strings.TrimSpace(req.Action)) {
	case "ping":
		return Response{OK: true, Ready: true}
	case "set":
		if len([]byte(req.Text)) > MaxClipboardTextBytes {
			return Response{Error: "clipboard text exceeds 1 MiB"}
		}
		if err := runTermux(ctx, cfg, runner, "termux-clipboard-set", req.Text, nil); err != nil {
			return Response{Error: err.Error()}
		}
		return Response{OK: true}
	case "get":
		var out string
		if err := runTermux(ctx, cfg, runner, "termux-clipboard-get", "", &out); err != nil {
			return Response{Error: err.Error()}
		}
		if len([]byte(out)) > MaxClipboardTextBytes {
			return Response{Error: "clipboard text exceeds 1 MiB"}
		}
		return Response{OK: true, Text: out}
	default:
		return Response{Error: "unsupported clipboard action: " + req.Action}
	}
}
func runTermux(ctx context.Context, cfg config.ChrootConfig, runner *sys.Runner, name, input string, out *string) error {
	cmd := filepath.Join(cfg.TermuxPrefix, "bin", name)
	if _, err := os.Stat(cmd); err != nil {
		return fmt.Errorf("missing Termux clipboard command: %s", cmd)
	}
	uid, gid, err := sys.HostTermuxUIDGID(cfg.TermuxHome)
	if err != nil {
		return err
	}
	if os.Geteuid() != 0 && os.Geteuid() != uid {
		return fmt.Errorf("clipboard bridge must run as root or Termux uid %d", uid)
	}
	opt := sys.RunOptions{Env: hostEnv(cfg), Input: input, Timeout: 5 * time.Second}
	if os.Geteuid() == 0 {
		opt.UID = &uid
		opt.GID = &gid
	}
	r, err := runner.Run(ctx, []string{cmd}, opt)
	if err != nil {
		return err
	}
	if out != nil {
		*out = r.Stdout
	}
	return nil
}

func socketRequest(ctx context.Context, socket string, req Request, token string) (Response, error) {
	if token == "" {
		data, err := os.ReadFile(tokenPath(socket))
		if err != nil {
			return Response{}, err
		}
		token = strings.TrimSpace(string(data))
	}
	req.Token = token
	d := net.Dialer{}
	raw, err := d.DialContext(ctx, "unix", socket)
	if err != nil {
		return Response{}, err
	}
	conn := raw.(*net.UnixConn)
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	wire, err := json.Marshal(req)
	if err != nil {
		return Response{}, err
	}
	if len(wire) > MaxClipboardWireBytes {
		return Response{}, errors.New("clipboard request exceeds wire limit")
	}
	if _, err = conn.Write(wire); err != nil {
		return Response{}, err
	}
	_ = conn.CloseWrite()
	data := make([]byte, 0, 4096)
	buf := make([]byte, 65536)
	for {
		n, e := conn.Read(buf)
		if n > 0 {
			data = append(data, buf[:n]...)
			if len(data) > MaxClipboardWireBytes {
				return Response{}, errors.New("clipboard response exceeds wire limit")
			}
		}
		if e != nil {
			break
		}
	}
	var resp Response
	if err = json.Unmarshal(data, &resp); err != nil {
		return Response{}, err
	}
	if !resp.OK {
		return resp, errors.New(resp.Error)
	}
	return resp, nil
}
func SocketSet(ctx context.Context, socket, text string) (Response, error) {
	return socketRequest(ctx, socket, Request{Action: "set", Text: text}, "")
}
func SocketGet(ctx context.Context, socket string) (Response, error) {
	return socketRequest(ctx, socket, Request{Action: "get"}, "")
}

func Doctor(cfg config.ChrootConfig, paths Paths) map[string]any {
	if paths.SocketPath == "" {
		paths = DefaultPaths(cfg)
	}
	d := DaemonStatus(paths.PIDFile)
	set := filepath.Join(cfg.TermuxPrefix, "bin", "termux-clipboard-set")
	get := filepath.Join(cfg.TermuxPrefix, "bin", "termux-clipboard-get")
	wr := map[string]bool{}
	for _, n := range []string{"termux-clip", "chrootctl-xsel", "chrootctl-xclip"} {
		_, e := os.Stat(filepath.Join(cfg.ChrootBase(), "usr/local/bin", n))
		wr[n] = e == nil
	}
	ready := true
	for _, v := range wr {
		ready = ready && v
	}
	_, se := os.Stat(paths.SocketPath)
	return map[string]any{"termux_clipboard_set": exists(set), "termux_clipboard_get": exists(get), "daemon_running": d["running"], "daemon_pid": d["pid"], "socket_path": paths.SocketPath, "socket_exists": se == nil, "chroot_socket_path": ChrootSocket, "wrappers": wr, "wrappers_ready": ready}
}
func exists(p string) bool { _, e := os.Stat(p); return e == nil }
