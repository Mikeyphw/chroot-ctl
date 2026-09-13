package system

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const (
	DefaultCaptureLimitBytes = 1024 * 1024
	PollInterval             = 100 * time.Millisecond
	TerminateGrace           = 2 * time.Second
)

var ChrootEnvBlocklist = []string{
	"LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "PYTHONPATH", "PREFIX",
	"TERMUX_VERSION", "TERMUX_APK_RELEASE", "ANDROID_ROOT", "ANDROID_DATA",
	"EXTERNAL_STORAGE", "TMPDIR", "TMP", "TEMP",
}

var ChrootEnvDefaults = map[string]string{
	"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
	"HOME": "/root", "USER": "root", "SHELL": "/bin/bash", "LANG": "C.UTF-8",
	"LC_ALL": "C.UTF-8", "TMPDIR": "/tmp", "TMP": "/tmp", "TEMP": "/tmp",
}

type Logger interface {
	Debugf(string, ...any)
	Infof(string, ...any)
}

type ProcessIdentity struct {
	PID            int     `json:"pid"`
	ProcessGroupID int     `json:"processGroupId"`
	StartTimeTicks *int64  `json:"processStartTime"`
	BootID         *string `json:"processBootId"`
}

type RunResult struct {
	ReturnCode     int    `json:"returncode"`
	Stdout         string `json:"stdout"`
	Stderr         string `json:"stderr"`
	TimedOut       bool   `json:"timed_out"`
	Cancelled      bool   `json:"cancelled"`
	Truncated      bool   `json:"truncated"`
	PID            *int   `json:"pid"`
	ProcessGroupID *int   `json:"process_group_id"`
}

type Runner struct {
	Logger    Logger
	DryRun    bool
	Register  func(ProcessIdentity)
	Cancelled func() bool
}

type RunOptions struct {
	Env             map[string]string
	CleanEnv        bool
	ChrootEnv       bool
	NoCapture       bool
	Cwd             string
	Input           string
	UID             *int
	GID             *int
	Background      bool
	Timeout         time.Duration
	MaxCaptureBytes int
	AllowFailure    bool
}

type SpawnOptions struct {
	Env        map[string]string
	CleanEnv   bool
	ChrootEnv  bool
	Cwd        string
	OutputPath string
	Append     bool
	UID        *int
	GID        *int
}

func QEMUUserBinaryNames(arch string) []string {
	switch arch {
	case "arm64":
		return []string{"qemu-aarch64-static", "qemu-arm64-static"}
	case "amd64":
		return []string{"qemu-x86_64-static", "qemu-amd64-static"}
	default:
		return []string{"qemu-" + arch + "-static"}
	}
}

func ProcessIdentityFromMap(value map[string]any) *ProcessIdentity {
	pid, ok := positiveInt(value["pid"])
	if !ok {
		return nil
	}
	pgRaw := value["processGroupId"]
	if pgRaw == nil {
		pgRaw = value["process_group_id"]
	}
	pgid, ok := positiveInt(pgRaw)
	if !ok {
		return nil
	}
	startRaw := value["processStartTime"]
	if startRaw == nil {
		startRaw = value["process_start_time"]
	}
	var start *int64
	if parsed, ok := integer64(startRaw); ok {
		start = &parsed
	}
	bootRaw := value["processBootId"]
	if bootRaw == nil {
		bootRaw = value["process_boot_id"]
	}
	var boot *string
	if bootRaw != nil {
		text := fmt.Sprint(bootRaw)
		if text != "" {
			boot = &text
		}
	}
	return &ProcessIdentity{PID: pid, ProcessGroupID: pgid, StartTimeTicks: start, BootID: boot}
}

func positiveInt(value any) (int, bool) {
	parsed, ok := integer64(value)
	return int(parsed), ok && parsed > 0
}
func integer64(value any) (int64, bool) {
	switch item := value.(type) {
	case int:
		return int64(item), true
	case int64:
		return item, true
	case float64:
		return int64(item), item == float64(int64(item))
	case string:
		parsed, err := strconv.ParseInt(item, 10, 64)
		return parsed, err == nil
	default:
		return 0, false
	}
}

func (p ProcessIdentity) Complete() bool {
	return p.PID > 0 && p.ProcessGroupID > 0 && p.StartTimeTicks != nil && p.BootID != nil && *p.BootID != ""
}

func CaptureProcessIdentity(pid int) *ProcessIdentity {
	if pid <= 0 {
		return nil
	}
	pgid, err := syscall.Getpgid(pid)
	if err != nil {
		return nil
	}
	start := processStartTimeTicks(pid)
	boot := bootID()
	return &ProcessIdentity{PID: pid, ProcessGroupID: pgid, StartTimeTicks: start, BootID: boot}
}

func ProcessIdentityMatches(identity ProcessIdentity) bool {
	if !identity.Complete() {
		return false
	}
	current := CaptureProcessIdentity(identity.PID)
	if current == nil || !current.Complete() {
		return false
	}
	return current.ProcessGroupID == identity.ProcessGroupID && *current.StartTimeTicks == *identity.StartTimeTicks && *current.BootID == *identity.BootID
}

func SignalProcessIdentity(identity ProcessIdentity, sig syscall.Signal) bool {
	if !ProcessIdentityMatches(identity) {
		return false
	}
	if err := syscall.Kill(-identity.ProcessGroupID, sig); err != nil {
		return false
	}
	return true
}

func TerminateProcessIdentity(identity ProcessIdentity, grace time.Duration) bool {
	if !ProcessIdentityMatches(identity) {
		return false
	}
	if !SignalProcessIdentity(identity, syscall.SIGTERM) {
		return false
	}
	if grace < 0 {
		grace = 0
	}
	deadline := time.Now().Add(grace)
	for time.Now().Before(deadline) {
		if !ProcessIdentityMatches(identity) {
			return true
		}
		time.Sleep(PollInterval)
	}
	if ProcessIdentityMatches(identity) {
		_ = SignalProcessIdentity(identity, syscall.SIGKILL)
	}
	return true
}

func (r Runner) debugf(format string, args ...any) {
	if r.Logger != nil {
		r.Logger.Debugf(format, args...)
	}
}
func (r Runner) infof(format string, args ...any) {
	if r.Logger != nil {
		r.Logger.Infof(format, args...)
	}
}

func (r Runner) Run(ctx context.Context, args []string, options RunOptions) (RunResult, error) {
	if len(args) == 0 {
		return RunResult{}, errors.New("command is empty")
	}
	r.debugf("run: %s", shellJoin(args))
	if r.DryRun {
		return RunResult{ReturnCode: 0}, nil
	}
	if options.Timeout < 0 {
		return RunResult{}, errors.New("timeout must be positive")
	}
	limit := options.MaxCaptureBytes
	if limit == 0 {
		limit = DefaultCaptureLimitBytes
	}
	if limit < 0 {
		return RunResult{}, errors.New("max_capture_bytes must not be negative")
	}
	if options.Background {
		return r.runBackground(args, options)
	}

	env := ProcessEnv(options.Env, options.CleanEnv, options.ChrootEnv)
	cmd := exec.Command(args[0], args[1:]...)
	cmd.Env = envList(env)
	if options.Cwd != "" {
		cmd.Dir = options.Cwd
	}
	cmd.SysProcAttr = processAttrs(options.UID, options.GID)
	if options.Input != "" {
		cmd.Stdin = strings.NewReader(options.Input)
	}

	var outFile, errFile *os.File
	var err error
	if !options.NoCapture {
		outFile, err = os.CreateTemp("", "chrootctl-stdout-*")
		if err != nil {
			return RunResult{}, err
		}
		defer closeRemove(outFile)
		errFile, err = os.CreateTemp("", "chrootctl-stderr-*")
		if err != nil {
			return RunResult{}, err
		}
		defer closeRemove(errFile)
		cmd.Stdout = outFile
		cmd.Stderr = errFile
	}
	if err := cmd.Start(); err != nil {
		return RunResult{}, err
	}
	identity := CaptureProcessIdentity(cmd.Process.Pid)
	if identity != nil && r.Register != nil {
		r.Register(*identity)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	started := time.Now()
	timedOut := false
	cancelled := false
	ticker := time.NewTicker(PollInterval)
	defer ticker.Stop()
	var waitErr error
waitLoop:
	for {
		select {
		case waitErr = <-done:
			break waitLoop
		case <-ctx.Done():
			cancelled = true
			r.terminateCommand(cmd, identity)
			waitErr = <-done
			break waitLoop
		case <-ticker.C:
			if r.Cancelled != nil && r.Cancelled() {
				cancelled = true
				r.terminateCommand(cmd, identity)
				waitErr = <-done
				break waitLoop
			}
			if options.Timeout > 0 && time.Since(started) >= options.Timeout {
				timedOut = true
				r.terminateCommand(cmd, identity)
				waitErr = <-done
				break waitLoop
			}
		}
	}
	result := RunResult{ReturnCode: exitCode(cmd.ProcessState, waitErr), TimedOut: timedOut, Cancelled: cancelled}
	pid := cmd.Process.Pid
	result.PID = &pid
	if identity != nil {
		pgid := identity.ProcessGroupID
		result.ProcessGroupID = &pgid
	}
	if !options.NoCapture {
		result.Stdout, _ = boundedFile(outFile, limit)
		result.Stderr, result.Truncated = boundedFile(errFile, limit)
		out, ot := boundedFile(outFile, limit)
		result.Stdout = out
		result.Truncated = result.Truncated || ot
	}
	if !options.AllowFailure && (cancelled || timedOut || result.ReturnCode != 0) {
		if cancelled {
			return result, errors.New("command cancelled")
		}
		if timedOut {
			return result, fmt.Errorf("command timed out after %gs", options.Timeout.Seconds())
		}
		msg := strings.TrimSpace(result.Stderr)
		if msg == "" {
			msg = "command failed: " + shellJoin(args)
		}
		return result, errors.New(msg)
	}
	return result, nil
}

func (r Runner) RunAttached(ctx context.Context, args []string, options RunOptions) (RunResult, error) {
	if len(args) == 0 {
		return RunResult{}, errors.New("command is empty")
	}
	r.debugf("run attached: %s", shellJoin(args))
	if r.DryRun {
		return RunResult{ReturnCode: 0}, nil
	}
	if options.Timeout < 0 {
		return RunResult{}, errors.New("timeout must be positive")
	}
	cmd := exec.Command(args[0], args[1:]...)
	cmd.Env = envList(ProcessEnv(options.Env, options.CleanEnv, options.ChrootEnv))
	if options.Cwd != "" {
		cmd.Dir = options.Cwd
	}
	cmd.SysProcAttr = processAttrs(options.UID, options.GID)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		return RunResult{}, err
	}
	identity := CaptureProcessIdentity(cmd.Process.Pid)
	if identity != nil && r.Register != nil {
		r.Register(*identity)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	started := time.Now()
	ticker := time.NewTicker(PollInterval)
	defer ticker.Stop()
	var waitErr error
	timedOut, cancelled := false, false
waitLoop:
	for {
		select {
		case waitErr = <-done:
			break waitLoop
		case <-ctx.Done():
			cancelled = true
			r.terminateCommand(cmd, identity)
			waitErr = <-done
			break waitLoop
		case <-ticker.C:
			if r.Cancelled != nil && r.Cancelled() {
				cancelled = true
				r.terminateCommand(cmd, identity)
				waitErr = <-done
				break waitLoop
			}
			if options.Timeout > 0 && time.Since(started) >= options.Timeout {
				timedOut = true
				r.terminateCommand(cmd, identity)
				waitErr = <-done
				break waitLoop
			}
		}
	}
	result := RunResult{ReturnCode: exitCode(cmd.ProcessState, waitErr), TimedOut: timedOut, Cancelled: cancelled}
	pid := cmd.Process.Pid
	result.PID = &pid
	if identity != nil {
		pgid := identity.ProcessGroupID
		result.ProcessGroupID = &pgid
	}
	if !options.AllowFailure && result.ReturnCode != 0 {
		if cancelled {
			return result, errors.New("command cancelled")
		}
		if timedOut {
			return result, fmt.Errorf("command timed out after %gs", options.Timeout.Seconds())
		}
		return result, fmt.Errorf("command failed with exit %d", result.ReturnCode)
	}
	return result, nil
}

func (r Runner) runBackground(args []string, options RunOptions) (RunResult, error) {
	cmd := exec.Command(args[0], args[1:]...)
	cmd.Env = envList(ProcessEnv(options.Env, options.CleanEnv, options.ChrootEnv))
	if options.Cwd != "" {
		cmd.Dir = options.Cwd
	}
	cmd.SysProcAttr = processAttrs(options.UID, options.GID)
	cmd.Stdin = nil
	if options.NoCapture {
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	} else {
		cmd.Stdout = nil
		cmd.Stderr = nil
	}
	if err := cmd.Start(); err != nil {
		return RunResult{}, err
	}
	identity := CaptureProcessIdentity(cmd.Process.Pid)
	if identity != nil && r.Register != nil {
		r.Register(*identity)
	}
	pid := cmd.Process.Pid
	result := RunResult{ReturnCode: 0, PID: &pid}
	if identity != nil {
		pg := identity.ProcessGroupID
		result.ProcessGroupID = &pg
	}
	_ = cmd.Process.Release()
	return result, nil
}

func (r Runner) Spawn(args []string, options SpawnOptions) (int, error) {
	if len(args) == 0 {
		return 0, errors.New("command is empty")
	}
	r.debugf("spawn: %s", shellJoin(args))
	if r.DryRun {
		return 0, nil
	}
	cmd := exec.Command(args[0], args[1:]...)
	cmd.Env = envList(ProcessEnv(options.Env, options.CleanEnv, options.ChrootEnv))
	if options.Cwd != "" {
		cmd.Dir = options.Cwd
	}
	cmd.SysProcAttr = processAttrs(options.UID, options.GID)
	cmd.Stdin = nil
	var output *os.File
	if options.OutputPath != "" {
		if err := os.MkdirAll(filepath.Dir(options.OutputPath), 0o755); err != nil {
			return 0, err
		}
		flags := os.O_CREATE | os.O_WRONLY | syscall.O_CLOEXEC | syscall.O_NOFOLLOW
		if options.Append {
			flags |= os.O_APPEND
		} else {
			flags |= os.O_TRUNC
		}
		f, err := os.OpenFile(options.OutputPath, flags, 0o600)
		if err != nil {
			return 0, err
		}
		output = f
		defer output.Close()
		cmd.Stdout = f
		cmd.Stderr = f
	}
	if err := cmd.Start(); err != nil {
		return 0, err
	}
	identity := CaptureProcessIdentity(cmd.Process.Pid)
	if identity != nil && r.Register != nil {
		r.Register(*identity)
	}
	pid := cmd.Process.Pid
	_ = cmd.Process.Release()
	return pid, nil
}

func (r Runner) Exec(args []string, options RunOptions) error {
	if len(args) == 0 {
		return errors.New("command is empty")
	}
	r.debugf("exec: %s", shellJoin(args))
	if r.DryRun {
		return nil
	}
	path, err := exec.LookPath(args[0])
	if err != nil {
		path = args[0]
	}
	return syscall.Exec(path, args, envList(ProcessEnv(options.Env, options.CleanEnv, options.ChrootEnv)))
}

func (r Runner) terminateCommand(cmd *exec.Cmd, identity *ProcessIdentity) {
	if identity != nil && TerminateProcessIdentity(*identity, TerminateGrace) {
		return
	}
	if cmd.Process != nil {
		_ = cmd.Process.Signal(syscall.SIGTERM)
		time.Sleep(50 * time.Millisecond)
		_ = cmd.Process.Kill()
	}
}

func IsRoot() bool { return os.Geteuid() == 0 }
func RequireRoot() error {
	if !IsRoot() {
		return errors.New("root privileges required")
	}
	return nil
}
func SudoAvailable() bool { return trustedSudoPath() != "" }
func SuAvailable() bool   { return trustedSuPath() != "" }

const (
	hostRootPath    = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
	androidRootPath = "/data/adb/chrootctl/bin:/system/bin:/system/xbin:/vendor/bin:/product/bin"
)

func firstExecutable(paths ...string) string {
	for _, path := range paths {
		st, err := os.Stat(path)
		if err == nil && st.Mode().IsRegular() && st.Mode()&0o111 != 0 {
			return path
		}
	}
	return ""
}

func trustedSudoPath() string { return firstExecutable("/usr/bin/sudo", "/bin/sudo") }
func trustedSuPath() string {
	return firstExecutable("/system/bin/su", "/system/xbin/su", "/sbin/su", "/debug_ramdisk/su")
}
func trustedEnvPath() string { return firstExecutable("/usr/bin/env", "/bin/env") }
func androidHost() bool {
	if os.Getenv("ANDROID_ROOT") != "" || os.Getenv("ANDROID_DATA") != "" {
		return true
	}
	_, err := os.Stat("/system/bin/app_process")
	return err == nil
}

// ReexecWithRootIO performs the privilege transition with caller-provided I/O.
// Provider binaries and the root PATH are fixed, never selected from caller
// PATH. Process-start failures are returned as errors; child exit statuses are
// returned only after the privileged command actually ran.
func (r Runner) ReexecWithRootIO(ctx context.Context, argv []string, stdin io.Reader, stdout, stderr io.Writer) (int, error) {
	if len(argv) == 0 {
		return 0, errors.New("re-exec argv is empty")
	}
	if r.DryRun {
		return 0, errors.New("internal error: dry-run must dispatch without privilege re-exec")
	}
	var cmd *exec.Cmd
	if sudo := trustedSudoPath(); sudo != "" && !androidHost() {
		envPath := trustedEnvPath()
		if envPath == "" {
			return 0, errors.New("trusted env executable is unavailable for sudo re-exec")
		}
		rootArgs := []string{envPath, "-i", "PATH=" + hostRootPath, "HOME=/root", "USER=root"}
		if term := os.Getenv("TERM"); term != "" {
			rootArgs = append(rootArgs, "TERM="+term)
		}
		rootArgs = append(rootArgs, argv...)
		cmd = exec.CommandContext(ctx, sudo, rootArgs...)
	} else if su := trustedSuPath(); su != "" {
		rootPath := hostRootPath
		home := "/root"
		if androidHost() {
			rootPath = androidRootPath
			home = "/data/adb/chrootctl"
		}
		prefix := []string{"export PATH=" + shellQuote(rootPath), "export HOME=" + shellQuote(home), "export USER=root"}
		command := strings.Join(prefix, "; ") + "; exec " + shellJoin(argv)
		cmd = exec.CommandContext(ctx, su, "-c", command)
	} else {
		return 0, errors.New("no trusted sudo/su provider is available and root is required")
	}
	cmd.Stdin = stdin
	cmd.Stdout = stdout
	cmd.Stderr = stderr
	err := cmd.Run()
	if err == nil {
		return 0, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.ExitCode(), nil
	}
	return 0, fmt.Errorf("root re-exec failed: %w", err)
}

// ReexecWithRoot retains the legacy process-global I/O API for internal callers.
func (r Runner) ReexecWithRoot(ctx context.Context, argv []string) (int, error) {
	return r.ReexecWithRootIO(ctx, argv, os.Stdin, os.Stdout, os.Stderr)
}

func (r Runner) ReexecWithSudo(ctx context.Context, argv []string) (int, error) {
	sudo := trustedSudoPath()
	if sudo == "" {
		return 0, errors.New("trusted sudo is not available and root is required")
	}
	if r.DryRun {
		return 0, errors.New("internal error: dry-run must dispatch without privilege re-exec")
	}
	cmd := exec.CommandContext(ctx, sudo, argv...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	err := cmd.Run()
	if err == nil {
		return 0, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.ExitCode(), nil
	}
	return 0, fmt.Errorf("sudo re-exec failed: %w", err)
}

// ReexecArgv returns an exact re-exec argv for the args supplied to cli.Run.
// On Android, privileged re-exec is allowed only through the active/root-managed
// production executable, never a Termux-writable development binary.
func ReexecArgv(args []string) ([]string, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	if androidHost() {
		trusted := firstExecutable(
			"/system/bin/chrootctl",
			"/data/adb/modules/chrootctl-magisk/system/bin/chrootctl",
			"/data/adb/ksu/modules/chrootctl-magisk/system/bin/chrootctl",
		)
		if trusted == "" {
			return nil, errors.New("trusted active chrootctl runtime is unavailable for root re-exec")
		}
		exe = trusted
	}
	return append([]string{exe}, args...), nil
}

func shellQuote(arg string) string { return "'" + strings.ReplaceAll(arg, "'", "'\\''") + "'" }

func MountTable(path string) (map[[2]string]struct{}, error) {
	if path == "" {
		path = "/proc/mounts"
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return map[[2]string]struct{}{}, nil
	}
	if err != nil {
		return nil, err
	}
	return ParseMountTable(string(data)), nil
}
func ParseMountTable(data string) map[[2]string]struct{} {
	out := map[[2]string]struct{}{}
	for _, line := range strings.Split(data, "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 2 {
			out[[2]string{fields[0], fields[1]}] = struct{}{}
		}
	}
	return out
}
func HostTermuxUIDGID(home string) (int, int, error) {
	info, err := os.Stat(home)
	if err != nil {
		return 0, 0, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return 0, 0, errors.New("filesystem does not expose uid/gid")
	}
	return int(stat.Uid), int(stat.Gid), nil
}
func HostArch() string {
	switch runtime.GOARCH {
	case "amd64":
		return "amd64"
	case "arm64":
		return "arm64"
	default:
		return runtime.GOARCH
	}
}
func CurrentUsername() (string, error) {
	u, err := user.LookupId(strconv.Itoa(os.Getuid()))
	if err == nil {
		return u.Username, nil
	}
	u, err = user.Current()
	if err != nil {
		return "", err
	}
	return u.Username, nil
}
func CommandExists(command string) bool { _, err := exec.LookPath(command); return err == nil }
func CanExecuteForeignArch(arch string) bool {
	found := false
	for _, name := range QEMUUserBinaryNames(arch) {
		if CommandExists(name) {
			found = true
			break
		}
	}
	if !found {
		return false
	}
	base := "/proc/sys/fs/binfmt_misc"
	if _, err := os.Stat(base); err != nil {
		return false
	}
	if raw, err := os.ReadFile(filepath.Join(base, "status")); err == nil {
		status := strings.ToLower(strings.TrimSpace(string(raw)))
		if status != "" && status != "1" && status != "enabled" {
			return false
		}
	}
	for _, name := range []string{"qemu-" + arch, "qemu-" + arch + "-static", arch, strings.ToUpper(arch)} {
		raw, err := os.ReadFile(filepath.Join(base, name))
		if err == nil && strings.Contains(strings.ToLower(string(raw)), "enabled") {
			return true
		}
	}
	return false
}

func ProcessEnv(overrides map[string]string, clean, chroot bool) map[string]string {
	env := map[string]string{}
	if !clean {
		for _, entry := range os.Environ() {
			if key, value, ok := strings.Cut(entry, "="); ok {
				env[key] = value
			}
		}
	}
	if chroot {
		for _, key := range ChrootEnvBlocklist {
			delete(env, key)
		}
		for key, value := range ChrootEnvDefaults {
			env[key] = value
		}
		term := os.Getenv("TERM")
		if term == "" {
			term = "xterm-256color"
		}
		env["TERM"] = term
	}
	for key, value := range overrides {
		env[key] = value
	}
	return env
}
func envList(env map[string]string) []string {
	keys := make([]string, 0, len(env))
	for key := range env {
		keys = append(keys, key)
	}
	sortStrings(keys)
	out := make([]string, 0, len(keys))
	for _, key := range keys {
		out = append(out, key+"="+env[key])
	}
	return out
}
func sortStrings(values []string) {
	for i := 1; i < len(values); i++ {
		for j := i; j > 0 && values[j] < values[j-1]; j-- {
			values[j], values[j-1] = values[j-1], values[j]
		}
	}
}
func processAttrs(uid, gid *int) *syscall.SysProcAttr {
	attrs := &syscall.SysProcAttr{Setpgid: true}
	if uid != nil || gid != nil {
		cred := &syscall.Credential{}
		if uid != nil {
			cred.Uid = uint32(*uid)
		} else {
			cred.Uid = uint32(os.Geteuid())
		}
		if gid != nil {
			cred.Gid = uint32(*gid)
		} else {
			cred.Gid = uint32(os.Getegid())
		}
		attrs.Credential = cred
	}
	return attrs
}
func processStartTimeTicks(pid int) *int64 {
	raw, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return nil
	}
	text := string(raw)
	index := strings.LastIndex(text, ")")
	if index < 0 {
		return nil
	}
	fields := strings.Fields(text[index+1:])
	if len(fields) <= 19 {
		return nil
	}
	value, err := strconv.ParseInt(fields[19], 10, 64)
	if err != nil {
		return nil
	}
	return &value
}
func bootID() *string {
	raw, err := os.ReadFile("/proc/sys/kernel/random/boot_id")
	if err != nil {
		return nil
	}
	value := strings.TrimSpace(string(raw))
	if value == "" {
		return nil
	}
	return &value
}
func boundedFile(file *os.File, max int) (string, bool) {
	if file == nil {
		return "", false
	}
	info, err := file.Stat()
	if err != nil {
		return "", false
	}
	size := info.Size()
	if max <= 0 {
		return "", size > 0
	}
	if size <= int64(max) {
		_, _ = file.Seek(0, io.SeekStart)
		raw, _ := io.ReadAll(file)
		return string(bytes.ToValidUTF8(raw, []byte("�"))), false
	}
	head := max / 2
	tail := max - head
	buf := make([]byte, head)
	_, _ = file.ReadAt(buf, 0)
	tailBuf := make([]byte, tail)
	_, _ = file.ReadAt(tailBuf, size-int64(tail))
	marker := fmt.Sprintf("\n... chrootctl capture truncated %d bytes ...\n", size-int64(max))
	return string(bytes.ToValidUTF8(append(append(buf, []byte(marker)...), tailBuf...), []byte("�"))), true
}
func closeRemove(file *os.File) {
	if file == nil {
		return
	}
	name := file.Name()
	_ = file.Close()
	_ = os.Remove(name)
}
func exitCode(state *os.ProcessState, err error) int {
	if state != nil {
		return state.ExitCode()
	}
	if err == nil {
		return 0
	}
	return -1
}
func shellJoin(args []string) string {
	parts := make([]string, len(args))
	for i, arg := range args {
		if arg == "" || strings.ContainsAny(arg, " \t\n'\"\\$`;&|<>*?()[]{}!") {
			parts[i] = "'" + strings.ReplaceAll(arg, "'", "'\\''") + "'"
		} else {
			parts[i] = arg
		}
	}
	return strings.Join(parts, " ")
}
