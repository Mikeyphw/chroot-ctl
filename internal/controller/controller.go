package controller

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"chrootctl/internal/config"
	"chrootctl/internal/model"
	sys "chrootctl/internal/system"
)

type Logger interface {
	Infof(string, ...any)
	Warningf(string, ...any)
}

type MountSpec struct {
	Source   string   `json:"source"`
	Target   string   `json:"target"`
	FSType   string   `json:"fstype,omitempty"`
	Options  []string `json:"options,omitempty"`
	Bind     bool     `json:"bind"`
	ReadOnly bool     `json:"read_only"`
}

type Controller struct {
	Config     config.ChrootConfig
	Runner     *sys.Runner
	Logger     Logger
	MountsPath string
}

func New(cfg config.ChrootConfig, runner *sys.Runner, logger Logger) *Controller {
	return &Controller{Config: cfg, Runner: runner, Logger: logger, MountsPath: "/proc/mounts"}
}

var controllerRequireRoot = func(r *sys.Runner) error {
	return r.RequireRoot()
}

func (c *Controller) resolvedShell() string {
	available := map[string]bool{}
	if _, err := os.Stat(filepath.Join(c.Config.ChrootBase(), strings.TrimPrefix(c.Config.ShellPath, "/"))); err == nil {
		available[c.Config.ShellPath] = true
	}
	if _, err := os.Stat(filepath.Join(c.Config.ChrootBase(), "bin/bash")); err == nil {
		available["/bin/bash"] = true
	}
	return c.Config.ResolvedShell(available)
}

func (c *Controller) ConfigMountSpecs(mounts []config.BindMount) []MountSpec {
	out := []MountSpec{}
	for _, m := range mounts {
		if m.Enabled {
			out = append(out, MountSpec{Source: m.Source, Target: filepath.Join(c.Config.ChrootBase(), m.Target), Bind: true, ReadOnly: m.ReadOnly})
		}
	}
	return out
}
func (c *Controller) MountSpecs() []MountSpec {
	base := c.Config.ChrootBase()
	specs := []MountSpec{
		// Android's host /dev commonly has no /dev/shm. Binding it over the guest
		// /dev hides the guest dev/pts and dev/shm directories, so subsequent
		// child mounts fail with ENOENT even though those paths existed before the
		// bind. Give the guest an independent /dev and populate the minimal device
		// nodes in FixTTY/EnsureDeviceNodes instead.
		{Source: "tmpfs", Target: filepath.Join(base, "dev"), FSType: "tmpfs", Options: []string{"mode=755", "nosuid"}}, {Source: "/sys", Target: filepath.Join(base, "sys"), Bind: true},
		{Source: "/proc", Target: filepath.Join(base, "proc"), Bind: true}, {Source: "devpts", Target: filepath.Join(base, "dev/pts"), FSType: "devpts"},
		{Source: "tmpfs", Target: filepath.Join(base, "dev/shm"), FSType: "tmpfs", Options: []string{"size=" + c.Config.DevShmSize, "mode=1777", "nosuid", "nodev"}},
		{Source: "/sdcard", Target: filepath.Join(base, "sdcard"), Bind: true},
		{Source: filepath.Join(c.Config.TermuxPrefix, "tmp"), Target: filepath.Join(base, "tmp"), Bind: true},
		{Source: c.Config.TermuxHome, Target: c.Config.TermuxHomeInChroot(), Bind: true},
	}
	specs = append(specs, c.ConfigMountSpecs(c.Config.MediaMounts)...)
	specs = append(specs, c.ConfigMountSpecs(c.Config.ExtraBindMounts)...)
	return specs
}
func (c *Controller) mountSpecsValidated() ([]MountSpec, error) {
	specs := c.MountSpecs()
	seen := map[string]string{}
	for _, spec := range specs {
		target := filepath.Clean(spec.Target)
		if previous, ok := seen[target]; ok {
			return nil, fmt.Errorf("duplicate mount target %s from %s and %s", target, previous, spec.Source)
		}
		seen[target] = spec.Source
	}
	return specs, nil
}

func (c *Controller) mountRecords() ([]sys.MountRecord, error) {
	path := c.MountsPath
	if path == "" {
		path = "/proc/mounts"
	}
	return sys.MountTableDetailed(path)
}

func mountRecordAt(records []sys.MountRecord, target string) *sys.MountRecord {
	target = filepath.Clean(target)
	for i := range records {
		if filepath.Clean(records[i].Target) == target {
			return &records[i]
		}
	}
	return nil
}

func sameFile(a, b string) bool {
	aa, errA := os.Stat(a)
	bb, errB := os.Stat(b)
	return errA == nil && errB == nil && os.SameFile(aa, bb)
}

func mountMatches(spec MountSpec, records []sys.MountRecord) (bool, error) {
	record := mountRecordAt(records, spec.Target)
	if record == nil {
		return false, nil
	}
	if spec.Bind {
		if filepath.Clean(record.Source) != filepath.Clean(spec.Source) && !sameFile(spec.Source, spec.Target) {
			return false, fmt.Errorf("mount target %s is occupied by unexpected source %s (expected %s)", spec.Target, record.Source, spec.Source)
		}
		if spec.ReadOnly && !record.Options["ro"] {
			return false, fmt.Errorf("mount target %s is writable but read-only bind is required", spec.Target)
		}
		return true, nil
	}
	if spec.FSType != "" && record.FSType != spec.FSType {
		return false, fmt.Errorf("mount target %s has filesystem %s (expected %s)", spec.Target, record.FSType, spec.FSType)
	}
	return true, nil
}

func (c *Controller) ensureDirs() error {
	if c.Runner != nil && c.Runner.DryRun {
		return nil
	}
	dirs := []string{filepath.Join(c.Config.ChrootBase(), "dev"), filepath.Join(c.Config.ChrootBase(), "dev/pts"), filepath.Join(c.Config.ChrootBase(), "dev/shm"), filepath.Join(c.Config.ChrootBase(), "sys"), filepath.Join(c.Config.ChrootBase(), "proc"), filepath.Join(c.Config.ChrootBase(), "tmp"), filepath.Join(c.Config.ChrootBase(), "sdcard"), c.Config.TermuxHomeInChroot(), c.Config.UserHomeInChroot()}
	for _, spec := range c.ConfigMountSpecs(c.Config.MediaMounts) {
		dirs = append(dirs, spec.Target)
	}
	for _, spec := range c.ConfigMountSpecs(c.Config.ExtraBindMounts) {
		dirs = append(dirs, spec.Target)
	}
	for _, dir := range dirs {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	return nil
}

func (c *Controller) ensureMountTarget(spec MountSpec) error {
	if c.Runner != nil && c.Runner.DryRun {
		return nil
	}
	// Parent mounts can hide directories created by ensureDirs. Re-create each
	// target immediately before its mount in the namespace where mount(2) runs.
	if err := os.MkdirAll(spec.Target, 0o755); err != nil {
		return fmt.Errorf("prepare mount target %s: %w", spec.Target, err)
	}
	st, err := os.Stat(spec.Target)
	if err != nil {
		return fmt.Errorf("MOUNT_TARGET_NOT_VISIBLE: target=%s source=%s fstype=%s: %w", spec.Target, spec.Source, spec.FSType, err)
	}
	if !st.IsDir() {
		return fmt.Errorf("MOUNT_TARGET_NOT_VISIBLE: target=%s source=%s fstype=%s: target is not a directory", spec.Target, spec.Source, spec.FSType)
	}
	return nil
}

func (c *Controller) run(ctx context.Context, args []string, opt sys.RunOptions) (sys.RunResult, error) {
	if c.Runner == nil {
		return sys.RunResult{}, errors.New("controller runner is nil")
	}
	return c.Runner.Run(ctx, args, opt)
}

func commandFailure(argv []string, result sys.RunResult, err error) error {
	if err != nil {
		return err
	}
	if result.ReturnCode == 0 {
		return nil
	}
	detail := strings.TrimSpace(result.Stderr)
	if detail == "" {
		detail = "command failed: " + strings.Join(argv, " ")
	}
	return errors.New(detail)
}

func (c *Controller) runRequired(ctx context.Context, argv []string, opt sys.RunOptions) error {
	result, err := c.run(ctx, argv, opt)
	return commandFailure(argv, result, err)
}

func relevantDataFlags(options map[string]bool) []string {
	pairs := [][]string{{"ro", "rw"}, {"suid", "nosuid"}, {"dev", "nodev"}, {"exec", "noexec"}}
	out := []string{}
	for _, pair := range pairs {
		if options[pair[0]] {
			out = append(out, pair[0])
		} else if options[pair[1]] {
			out = append(out, pair[1])
		}
	}
	return out
}

func replaceMountFlag(flags []string, positive, negative string) []string {
	out := make([]string, 0, len(flags)+1)
	for _, flag := range flags {
		if flag != positive && flag != negative {
			out = append(out, flag)
		}
	}
	return append(out, positive)
}

func (c *Controller) withDataDevSuid(ctx context.Context) (func() error, error) {
	if c.Runner != nil && c.Runner.DryRun {
		return func() error { return nil }, nil
	}
	if !c.Config.MountDataWithDevSuid {
		return func() error { return nil }, nil
	}
	records, err := c.mountRecords()
	if err != nil {
		return nil, fmt.Errorf("read mount table before /data remount: %w", err)
	}
	record := mountRecordAt(records, "/data")
	if record == nil {
		return nil, errors.New("/data mount not found; refusing global remount")
	}
	original := relevantDataFlags(record.Options)
	wanted := replaceMountFlag(replaceMountFlag(append([]string(nil), original...), "dev", "nodev"), "suid", "nosuid")
	if err := c.runRequired(ctx, []string{"busybox", "mount", "-o", "remount," + strings.Join(wanted, ","), "/data"}, sys.RunOptions{MaxCaptureBytes: 64 * 1024}); err != nil {
		return nil, fmt.Errorf("temporarily remount /data dev,suid: %w", err)
	}
	return func() error {
		if c.Runner != nil && c.Runner.DryRun {
			return nil
		}
		flags := original
		if len(flags) == 0 {
			flags = []string{"rw"}
		}
		if err := c.runRequired(context.Background(), []string{"busybox", "mount", "-o", "remount," + strings.Join(flags, ","), "/data"}, sys.RunOptions{MaxCaptureBytes: 64 * 1024}); err != nil {
			return fmt.Errorf("restore /data mount flags: %w", err)
		}
		return nil
	}, nil
}

func (c *Controller) rollbackMounts(ctx context.Context, targets []string) []string {
	errs := []string{}
	for i := len(targets) - 1; i >= 0; i-- {
		argv := []string{"busybox", "umount", targets[i]}
		if err := c.runRequired(ctx, argv, sys.RunOptions{AllowFailure: true, MaxCaptureBytes: 64 * 1024}); err != nil {
			errs = append(errs, fmt.Sprintf("rollback %s: %v", targets[i], err))
		}
	}
	return errs
}

func (c *Controller) Mount(ctx context.Context) model.OperationResult {
	result := model.OperationResult{}
	if c.Runner == nil {
		result.AddFailure("controller runner is nil")
		return result
	}
	if err := controllerRequireRoot(c.Runner); err != nil {
		result.AddFailure(err.Error())
		return result
	}
	specs, err := c.mountSpecsValidated()
	if err != nil {
		result.AddFailure(err.Error())
		return result
	}
	if err := c.ensureDirs(); err != nil {
		result.AddFailure(err.Error())
		return result
	}
	restoreData, err := c.withDataDevSuid(ctx)
	if err != nil {
		result.AddFailure(err.Error())
		return result
	}
	created := []string{}
	defer func() {
		if restoreData != nil {
			if err := restoreData(); err != nil {
				result.AddFailure(err.Error())
			}
		}
	}()
	for _, spec := range specs {
		records, readErr := c.mountRecords()
		if readErr != nil {
			result.AddFailure(readErr.Error())
			rollbackErrs := c.rollbackMounts(ctx, created)
			result.Errors = append(result.Errors, rollbackErrs...)
			result.Failed += len(rollbackErrs)
			break
		}
		ok, matchErr := mountMatches(spec, records)
		if matchErr != nil {
			result.AddFailure(matchErr.Error())
			result.Errors = append(result.Errors, c.rollbackMounts(ctx, created)...)
			break
		}
		if ok {
			result.AddSkipped()
			continue
		}
		if err := c.ensureMountTarget(spec); err != nil {
			result.AddFailure(err.Error())
			result.Errors = append(result.Errors, c.rollbackMounts(ctx, created)...)
			break
		}
		var argv []string
		if spec.Bind {
			argv = []string{"busybox", "mount", "--bind", spec.Source, spec.Target}
		} else {
			argv = []string{"busybox", "mount", "-t", spec.FSType}
			if len(spec.Options) > 0 {
				argv = append(argv, "-o", strings.Join(spec.Options, ","))
			}
			argv = append(argv, spec.Source, spec.Target)
		}
		if err := c.runRequired(ctx, argv, sys.RunOptions{MaxCaptureBytes: 64 * 1024}); err != nil {
			result.AddFailure(err.Error())
			result.Errors = append(result.Errors, c.rollbackMounts(ctx, created)...)
			break
		}
		created = append(created, spec.Target)
		if spec.Bind && spec.ReadOnly {
			if err := c.runRequired(ctx, []string{"busybox", "mount", "-o", "remount,bind,ro", spec.Target}, sys.RunOptions{MaxCaptureBytes: 64 * 1024}); err != nil {
				result.AddFailure(err.Error())
				result.Errors = append(result.Errors, c.rollbackMounts(ctx, created)...)
				break
			}
		}
		if c.Runner == nil || !c.Runner.DryRun {
			records, readErr = c.mountRecords()
			if readErr != nil {
				result.AddFailure(readErr.Error())
				result.Errors = append(result.Errors, c.rollbackMounts(ctx, created)...)
				break
			}
			if ok, verifyErr := mountMatches(spec, records); verifyErr != nil || !ok {
				if verifyErr == nil {
					verifyErr = fmt.Errorf("mount %s was not visible after mount", spec.Target)
				}
				result.AddFailure(verifyErr.Error())
				result.Errors = append(result.Errors, c.rollbackMounts(ctx, created)...)
				break
			}
		}
		result.AddSuccess()
	}
	return result
}

func (c *Controller) Unmount(ctx context.Context) model.OperationResult {
	result := model.OperationResult{}
	if c.Runner == nil {
		result.AddFailure("controller runner is nil")
		return result
	}
	if err := controllerRequireRoot(c.Runner); err != nil {
		result.AddFailure(err.Error())
		return result
	}
	specs, err := c.mountSpecsValidated()
	if err != nil {
		result.AddFailure(err.Error())
		return result
	}
	for i := len(specs) - 1; i >= 0; i-- {
		records, readErr := c.mountRecords()
		if readErr != nil {
			result.AddFailure(readErr.Error())
			break
		}
		ok, matchErr := mountMatches(specs[i], records)
		if matchErr != nil {
			result.AddFailure(matchErr.Error())
			continue
		}
		if !ok {
			result.AddSkipped()
			continue
		}
		if err := c.runRequired(ctx, []string{"busybox", "umount", specs[i].Target}, sys.RunOptions{AllowFailure: true, MaxCaptureBytes: 64 * 1024}); err != nil {
			result.AddFailure(err.Error())
		} else {
			result.AddSuccess()
		}
	}
	return result
}

func (c *Controller) FixTTY(ctx context.Context) model.OperationResult {
	result := model.OperationResult{}
	if c.Runner == nil {
		result.AddFailure("controller runner is nil")
		return result
	}
	if err := c.Runner.RequireRoot(); err != nil {
		result.AddFailure(err.Error())
		return result
	}
	records, err := c.mountRecords()
	if err != nil {
		result.AddFailure(err.Error())
		return result
	}
	dev := MountSpec{Source: "tmpfs", Target: filepath.Join(c.Config.ChrootBase(), "dev"), FSType: "tmpfs"}
	ok, matchErr := mountMatches(dev, records)
	if matchErr != nil {
		result.AddFailure(matchErr.Error())
		return result
	}
	if !ok {
		result.AddFailure(fmt.Sprintf("MOUNT_TARGET_NOT_VISIBLE: target=%s source=tmpfs fstype=tmpfs: private guest /dev is not mounted", dev.Target))
		return result
	}
	// /dev is a fresh tmpfs, so its essential device nodes and conventional
	// links must be populated after the mount. Returning early here leaves the
	// guest with only the child mountpoints and makes /dev/null, /dev/tty, etc.
	// unavailable inside the chroot.
	return c.EnsureDeviceNodes(ctx)
}

func (c *Controller) EnsureDeviceNodes(ctx context.Context) model.OperationResult {
	result := model.OperationResult{}
	if c.Runner == nil {
		result.AddFailure("controller runner is nil")
		return result
	}
	if err := c.Runner.RequireRoot(); err != nil {
		result.AddFailure(err.Error())
		return result
	}
	nodes := map[string][3]string{"tty": {"5", "0", "666"}, "console": {"5", "1", "600"}, "null": {"1", "3", "666"}, "zero": {"1", "5", "666"}, "random": {"1", "8", "644"}, "urandom": {"1", "9", "644"}}
	dev := filepath.Join(c.Config.ChrootBase(), "dev")
	if c.Runner == nil || !c.Runner.DryRun {
		if err := os.MkdirAll(dev, 0o755); err != nil {
			result.AddFailure(err.Error())
			return result
		}
		for _, dir := range []string{"pts", "shm"} {
			if err := os.MkdirAll(filepath.Join(dev, dir), 0o755); err != nil {
				result.AddFailure(err.Error())
				return result
			}
		}
	}
	for name, value := range nodes {
		target := filepath.Join(dev, name)
		if _, err := os.Stat(target); err == nil {
			result.AddSkipped()
			continue
		}
		if err := c.runRequired(ctx, []string{"busybox", "mknod", "-m", value[2], target, "c", value[0], value[1]}, sys.RunOptions{MaxCaptureBytes: 64 * 1024}); err != nil {
			result.AddFailure(err.Error())
		} else {
			result.AddSuccess()
		}
	}
	if c.Runner == nil || !c.Runner.DryRun {
		links := map[string]string{
			"fd": "/proc/self/fd", "stdin": "/proc/self/fd/0",
			"stdout": "/proc/self/fd/1", "stderr": "/proc/self/fd/2",
			"ptmx": "pts/ptmx",
		}
		for name, target := range links {
			path := filepath.Join(dev, name)
			if _, err := os.Lstat(path); err == nil {
				continue
			} else if !os.IsNotExist(err) {
				result.AddFailure(err.Error())
				continue
			}
			if err := os.Symlink(target, path); err != nil {
				result.AddFailure(err.Error())
			} else {
				result.AddSuccess()
			}
		}
	}
	return result
}

// BindHostDevices is retained for callers compiled against the old API. CHR08
// deliberately avoids persistent child bind mounts under an already-bound /dev.
func (c *Controller) BindHostDevices(ctx context.Context) model.OperationResult { return c.FixTTY(ctx) }

func (c *Controller) SessionEnv(root, x11 bool, username string) map[string]string {
	user := username
	if root {
		user = "root"
	} else if user == "" {
		user = c.Config.Username
	}
	env := map[string]string{"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/home/" + user, "USER": user, "SHELL": c.resolvedShell(), "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
	if root {
		env["HOME"] = "/root"
	}
	if x11 {
		env["DISPLAY"] = ":0"
		env["PULSE_SERVER"] = "tcp:127.0.0.1:4713"
	}
	return env
}
func shellQuote(s string) string {
	if s == "" {
		return "''"
	}
	if !strings.ContainsAny(s, " \t\n'\"\\$`!&|;()<>*?[]{}") {
		return s
	}
	return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'"
}
func ShellJoin(argv []string) string {
	out := make([]string, len(argv))
	for i, v := range argv {
		out[i] = shellQuote(v)
	}
	return strings.Join(out, " ")
}
func (c *Controller) ExecInvocation(root bool, argv []string, command string, x11 bool, username string) ([]string, map[string]string, error) {
	if command == "" && len(argv) == 0 {
		return nil, nil, errors.New("no command specified")
	}
	user := username
	if root {
		user = "root"
	} else if user == "" {
		user = c.Config.Username
	}
	shell := c.resolvedShell()
	text := command
	if text == "" {
		text = ShellJoin(argv)
	}
	var out []string
	if root {
		flag := "-lc"
		if x11 {
			flag = "-ilc"
		}
		out = []string{"chroot", c.Config.ChrootBase(), shell, flag, text}
	} else if x11 {
		launch := "export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713; exec " + shell + " -ilc " + shellQuote(text)
		out = []string{"chroot", c.Config.ChrootBase(), "/bin/su", "-", user, "-c", launch}
	} else {
		out = []string{"chroot", c.Config.ChrootBase(), "/bin/su", "-", user, "-c", text}
	}
	return out, c.SessionEnv(root, x11, user), nil
}
func (c *Controller) LoginInvocation(root, x11 bool, username string) ([]string, map[string]string, error) {
	user := username
	if root {
		user = "root"
	} else if user == "" {
		user = c.Config.Username
	}
	shell := c.resolvedShell()
	if shell == "" {
		return nil, nil, errors.New("no usable shell found in chroot")
	}
	env := c.SessionEnv(root, x11, user)
	if root {
		flag := "-l"
		if x11 {
			flag = "-il"
		}
		return []string{"chroot", c.Config.ChrootBase(), shell, flag}, env, nil
	}
	if x11 {
		launch := "export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713; exec " + shell + " -il"
		return []string{"chroot", c.Config.ChrootBase(), "/bin/su", "-", user, "-c", launch}, env, nil
	}
	return []string{"chroot", c.Config.ChrootBase(), "/bin/su", "-", user}, env, nil
}

func (c *Controller) ServiceInvocation(root bool, command string, x11 bool, username string) ([]string, map[string]string, error) {
	if command == "" {
		return nil, nil, errors.New("no service command specified")
	}
	user := username
	if root {
		user = "root"
	} else if user == "" {
		user = c.Config.Username
	}
	shell := c.resolvedShell()
	env := c.SessionEnv(root, x11, user)
	if root {
		return []string{"chroot", c.Config.ChrootBase(), shell, "-ilc", command}, env, nil
	}
	prefix := ""
	if x11 {
		prefix = "export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713; "
	}
	launch := prefix + "exec " + shell + " -ilc " + shellQuote(command)
	return []string{"chroot", c.Config.ChrootBase(), "/bin/su", "-", user, "-c", launch}, env, nil
}
func requireResult(label string, r model.OperationResult) error {
	if r.Failed == 0 {
		return nil
	}
	detail := strings.Join(r.Errors, "; ")
	if detail == "" {
		detail = fmt.Sprintf("%d operation(s) failed", r.Failed)
	}
	return fmt.Errorf("%s failed: %s", label, detail)
}
func (c *Controller) Prepare(ctx context.Context, x11 bool) error {
	if err := c.Runner.RequireRoot(); err != nil {
		return err
	}
	if err := requireResult("mount", c.Mount(ctx)); err != nil {
		return err
	}
	if err := requireResult("tty preparation", c.FixTTY(ctx)); err != nil {
		return err
	}
	if x11 {
		return c.PrepareX11Host(ctx)
	}
	return nil
}
func (c *Controller) PrepareX11Host(ctx context.Context) error {
	uid, gid, err := sys.HostTermuxUIDGID(c.Config.TermuxHome)
	if err != nil {
		return err
	}
	am, err := exec.LookPath("am")
	if err != nil {
		return errors.New("Android activity manager command 'am' is required for X11")
	}
	env := map[string]string{"HOME": c.Config.TermuxHome, "PREFIX": c.Config.TermuxPrefix, "TMPDIR": filepath.Join(c.Config.TermuxPrefix, "tmp"), "PATH": filepath.Join(c.Config.TermuxPrefix, "bin") + ":/system/bin:/system/xbin:/vendor/bin", "LD_LIBRARY_PATH": filepath.Join(c.Config.TermuxPrefix, "lib")}
	if err := c.runRequired(ctx, []string{am, "start", "--user", "0", "-n", "com.termux.x11/com.termux.x11.MainActivity"}, sys.RunOptions{OutputPolicy: sys.OutputDiscard, MaxCaptureBytes: 64 * 1024}); err != nil {
		return fmt.Errorf("start Termux:X11 activity: %w", err)
	}
	pulse := filepath.Join(c.Config.TermuxPrefix, "bin", "pulseaudio")
	if st, e := os.Stat(pulse); e != nil || !st.Mode().IsRegular() || st.Mode()&0o111 == 0 {
		return fmt.Errorf("PulseAudio executable unavailable at %s", pulse)
	}
	if err := c.runRequired(ctx, []string{pulse, "--start", "--exit-idle-time=-1"}, sys.RunOptions{OutputPolicy: sys.OutputDiscard, Env: env, UID: &uid, GID: &gid, MaxCaptureBytes: 64 * 1024}); err != nil {
		return fmt.Errorf("start PulseAudio: %w", err)
	}
	x11 := filepath.Join(c.Config.TermuxPrefix, "bin", "termux-x11")
	if st, e := os.Stat(x11); e != nil || !st.Mode().IsRegular() || st.Mode()&0o111 == 0 {
		return fmt.Errorf("termux-x11 executable unavailable at %s", x11)
	}
	if _, err := c.run(ctx, []string{x11, ":0", "-ac"}, sys.RunOptions{OutputPolicy: sys.OutputDiscard, Env: env, UID: &uid, GID: &gid, Background: true}); err != nil {
		return fmt.Errorf("start termux-x11: %w", err)
	}
	return nil
}
func (c *Controller) X11HostCommands() []string {
	return []string{"am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity", filepath.Join(c.Config.TermuxPrefix, "bin/pulseaudio") + " --start --exit-idle-time=-1", filepath.Join(c.Config.TermuxPrefix, "bin/termux-x11") + " :0 -ac &"}
}
func (c *Controller) StatusChecked(verbose bool) ([]map[string]string, error) {
	specs, err := c.mountSpecsValidated()
	if err != nil {
		return nil, err
	}
	records, err := c.mountRecords()
	if err != nil {
		return nil, err
	}
	rows := []map[string]string{}
	for _, spec := range specs {
		typ := spec.FSType
		if spec.Bind {
			typ = "bind"
			if spec.ReadOnly {
				typ = "bind:ro"
			}
		}
		row := map[string]string{"source": spec.Source, "target": spec.Target, "type": typ, "mounted": "no"}
		ok, matchErr := mountMatches(spec, records)
		if matchErr != nil {
			row["mounted"] = "mismatch"
			row["error"] = matchErr.Error()
		} else if ok {
			row["mounted"] = "yes"
		}
		if verbose {
			if _, e := os.Stat(spec.Target); e == nil {
				row["target_exists"] = "yes"
			} else {
				row["target_exists"] = "no"
			}
			if _, e := os.Stat(spec.Source); e == nil {
				row["source_exists"] = "yes"
			} else {
				row["source_exists"] = "n/a"
			}
		}
		rows = append(rows, row)
	}
	return rows, nil
}
func (c *Controller) Status(verbose bool) []map[string]string {
	rows, err := c.StatusChecked(verbose)
	if err != nil {
		return []map[string]string{{"source": "mount_table", "target": c.MountsPath, "mounted": "error", "error": err.Error()}}
	}
	return rows
}
func (c *Controller) DoctorChecked() ([]map[string]string, error) {
	which := func(x string) string { p, _ := exec.LookPath(x); return p }
	shell := c.resolvedShell()
	base := c.Config.ChrootBase()
	rootStatus, rootDetail := "warning", "sudo required"
	if sys.IsRoot() {
		rootStatus, rootDetail = "ok", "running as root"
	}
	rows := []map[string]string{{"check": "busybox", "status": map[bool]string{true: "ok", false: "missing"}[which("busybox") != ""], "detail": which("busybox")}, {"check": "chroot", "status": map[bool]string{true: "ok", false: "missing"}[which("chroot") != ""], "detail": which("chroot")}, {"check": "shell", "status": "missing", "detail": shell}, {"check": "chroot_base", "status": "missing", "detail": base}, {"check": "root", "status": rootStatus, "detail": rootDetail}}
	if _, e := os.Stat(filepath.Join(base, strings.TrimPrefix(shell, "/"))); e == nil {
		rows[2]["status"] = "ok"
	}
	if _, e := os.Stat(base); e == nil {
		rows[3]["status"] = "ok"
	}
	statusRows, err := c.StatusChecked(false)
	if err != nil {
		return rows, err
	}
	mounted := 0
	mismatch := 0
	for _, row := range statusRows {
		if row["mounted"] == "yes" {
			mounted++
		} else if row["mounted"] == "mismatch" {
			mismatch++
		}
	}
	mountStatus := "missing"
	if mounted == len(statusRows) && mismatch == 0 {
		mountStatus = "ok"
	}
	rows = append(rows, map[string]string{"check": "mounts", "status": mountStatus, "detail": fmt.Sprintf("%d/%d mounted; %d mismatched", mounted, len(statusRows), mismatch)})
	return rows, nil
}
func (c *Controller) Doctor() []map[string]string {
	rows, err := c.DoctorChecked()
	if err != nil {
		return append(rows, map[string]string{"check": "mount_table", "status": "missing", "detail": err.Error()})
	}
	return rows
}
