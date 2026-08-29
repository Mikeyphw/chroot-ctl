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
		{Source: "/dev", Target: filepath.Join(base, "dev"), Bind: true}, {Source: "/sys", Target: filepath.Join(base, "sys"), Bind: true},
		{Source: "/proc", Target: filepath.Join(base, "proc"), Bind: true}, {Source: "devpts", Target: filepath.Join(base, "dev/pts"), FSType: "devpts"},
		{Source: "tmpfs", Target: filepath.Join(base, "dev/shm"), FSType: "tmpfs", Options: []string{"size=" + c.Config.DevShmSize}},
		{Source: "/sdcard", Target: filepath.Join(base, "sdcard"), Bind: true},
		{Source: filepath.Join(c.Config.TermuxPrefix, "tmp"), Target: filepath.Join(base, "tmp"), Bind: true},
		{Source: c.Config.TermuxHome, Target: c.Config.TermuxHomeInChroot(), Bind: true},
	}
	specs = append(specs, c.ConfigMountSpecs(c.Config.MediaMounts)...)
	specs = append(specs, c.ConfigMountSpecs(c.Config.ExtraBindMounts)...)
	return specs
}
func mounted(spec MountSpec, table map[[2]string]struct{}) bool {
	if _, ok := table[[2]string{spec.Source, spec.Target}]; ok {
		return true
	}
	for pair := range table {
		if pair[1] == spec.Target {
			return true
		}
	}
	return false
}
func (c *Controller) mountTable() (map[[2]string]struct{}, error) {
	path := c.MountsPath
	if path == "" {
		path = "/proc/mounts"
	}
	return sys.MountTable(path)
}
func (c *Controller) ensureDirs() error {
	if c.Runner != nil && c.Runner.DryRun {
		return nil
	}
	dirs := []string{filepath.Join(c.Config.ChrootBase(), "dev"), filepath.Join(c.Config.ChrootBase(), "dev/pts"), filepath.Join(c.Config.ChrootBase(), "dev/shm"), filepath.Join(c.Config.ChrootBase(), "sys"), filepath.Join(c.Config.ChrootBase(), "proc"), filepath.Join(c.Config.ChrootBase(), "tmp"), filepath.Join(c.Config.ChrootBase(), "sdcard"), c.Config.TermuxHomeInChroot(), c.Config.UserHomeInChroot()}
	for _, s := range c.ConfigMountSpecs(c.Config.MediaMounts) {
		dirs = append(dirs, s.Target)
	}
	for _, s := range c.ConfigMountSpecs(c.Config.ExtraBindMounts) {
		dirs = append(dirs, s.Target)
	}
	for _, d := range dirs {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	return nil
}
func (c *Controller) run(ctx context.Context, args []string, opt sys.RunOptions) (sys.RunResult, error) {
	if c.Runner == nil {
		return sys.RunResult{}, errors.New("controller runner is nil")
	}
	return c.Runner.Run(ctx, args, opt)
}

func (c *Controller) Mount(ctx context.Context) model.OperationResult {
	r := model.OperationResult{}
	if err := sys.RequireRoot(); err != nil {
		r.AddFailure(err.Error())
		return r
	}
	if err := c.ensureDirs(); err != nil {
		r.AddFailure(err.Error())
		return r
	}
	table, err := c.mountTable()
	if err != nil {
		r.AddFailure(err.Error())
		return r
	}
	if c.Config.MountDataWithDevSuid {
		_, _ = c.run(ctx, []string{"busybox", "mount", "-o", "remount,dev,suid", "/data"}, sys.RunOptions{AllowFailure: true})
	}
	for _, s := range c.MountSpecs() {
		if mounted(s, table) {
			r.AddSkipped()
			continue
		}
		var argv []string
		if s.Bind {
			argv = []string{"busybox", "mount", "--bind", s.Source, s.Target}
		} else {
			argv = []string{"busybox", "mount", "-t", s.FSType}
			if len(s.Options) > 0 {
				argv = append(argv, "-o", strings.Join(s.Options, ","))
			}
			argv = append(argv, s.Source, s.Target)
		}
		if _, err := c.run(ctx, argv, sys.RunOptions{}); err != nil {
			r.AddFailure(err.Error())
			break
		}
		if s.Bind && s.ReadOnly {
			if _, err := c.run(ctx, []string{"busybox", "mount", "-o", "remount,bind,ro", s.Target}, sys.RunOptions{}); err != nil {
				r.AddFailure(err.Error())
				break
			}
		}
		r.AddSuccess()
	}
	return r
}
func (c *Controller) Unmount(ctx context.Context) model.OperationResult {
	r := model.OperationResult{}
	if err := sys.RequireRoot(); err != nil {
		r.AddFailure(err.Error())
		return r
	}
	table, err := c.mountTable()
	if err != nil {
		r.AddFailure(err.Error())
		return r
	}
	specs := c.MountSpecs()
	for i := len(specs) - 1; i >= 0; i-- {
		s := specs[i]
		if !mounted(s, table) {
			r.AddSkipped()
			continue
		}
		res, err := c.run(ctx, []string{"busybox", "umount", s.Target}, sys.RunOptions{AllowFailure: true})
		if err != nil {
			r.AddFailure(err.Error())
		} else if res.ReturnCode != 0 {
			detail := strings.TrimSpace(res.Stderr)
			if detail == "" {
				detail = "command failed: busybox umount " + s.Target
			}
			r.AddFailure(detail)
		} else {
			r.AddSuccess()
		}
	}
	return r
}
func (c *Controller) FixTTY(ctx context.Context) model.OperationResult {
	a := c.EnsureDeviceNodes(ctx)
	b := c.BindHostDevices(ctx)
	return model.OperationResult{Success: a.Success + b.Success, Failed: a.Failed + b.Failed, Skipped: a.Skipped + b.Skipped, Errors: append(a.Errors, b.Errors...)}
}
func (c *Controller) EnsureDeviceNodes(ctx context.Context) model.OperationResult {
	r := model.OperationResult{}
	if err := sys.RequireRoot(); err != nil {
		r.AddFailure(err.Error())
		return r
	}
	nodes := map[string][3]string{"tty": {"5", "0", "666"}, "console": {"5", "1", "600"}, "null": {"1", "3", "666"}, "zero": {"1", "5", "666"}, "random": {"1", "8", "644"}, "urandom": {"1", "9", "644"}}
	dev := filepath.Join(c.Config.ChrootBase(), "dev")
	if c.Runner == nil || !c.Runner.DryRun {
		_ = os.MkdirAll(dev, 0o755)
	}
	for name, v := range nodes {
		target := filepath.Join(dev, name)
		if _, err := os.Stat(target); err == nil {
			r.AddSkipped()
			continue
		}
		if _, err := c.run(ctx, []string{"busybox", "mknod", "-m", v[2], target, "c", v[0], v[1]}, sys.RunOptions{}); err != nil {
			r.AddFailure(err.Error())
		} else {
			r.AddSuccess()
		}
	}
	return r
}
func (c *Controller) BindHostDevices(ctx context.Context) model.OperationResult {
	r := model.OperationResult{}
	if err := sys.RequireRoot(); err != nil {
		r.AddFailure(err.Error())
		return r
	}
	for _, name := range []string{"tty", "console", "null", "random", "urandom"} {
		src := filepath.Join("/dev", name)
		if _, err := os.Stat(src); err != nil {
			r.AddSkipped()
			continue
		}
		dst := filepath.Join(c.Config.ChrootBase(), "dev", name)
		res, err := c.run(ctx, []string{"busybox", "mount", "--bind", src, dst}, sys.RunOptions{AllowFailure: true})
		if err != nil || res.ReturnCode != 0 {
			detail := ""
			if err != nil {
				detail = err.Error()
			} else {
				detail = strings.TrimSpace(res.Stderr)
			}
			if detail == "" {
				detail = "command failed: busybox mount --bind " + src + " " + dst
			}
			r.AddFailure(detail)
		} else {
			r.AddSuccess()
		}
	}
	return r
}

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
	if err := sys.RequireRoot(); err != nil {
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
	_, _ = c.run(ctx, []string{"am", "start", "--user", "0", "-n", "com.termux.x11/com.termux.x11.MainActivity"}, sys.RunOptions{AllowFailure: true, NoCapture: true})
	env := map[string]string{"HOME": c.Config.TermuxHome, "PREFIX": c.Config.TermuxPrefix, "TMPDIR": filepath.Join(c.Config.TermuxPrefix, "tmp"), "PATH": filepath.Join(c.Config.TermuxPrefix, "bin") + ":/system/bin:/system/xbin:/vendor/bin", "LD_LIBRARY_PATH": filepath.Join(c.Config.TermuxPrefix, "lib")}
	p := filepath.Join(c.Config.TermuxPrefix, "bin", "pulseaudio")
	if _, e := os.Stat(p); e == nil {
		_, _ = c.run(ctx, []string{p, "--start", "--exit-idle-time=-1"}, sys.RunOptions{AllowFailure: true, NoCapture: true, Env: env, UID: &uid, GID: &gid})
	}
	x := filepath.Join(c.Config.TermuxPrefix, "bin", "termux-x11")
	if _, e := os.Stat(x); e == nil {
		_, _ = c.run(ctx, []string{x, ":0", "-ac"}, sys.RunOptions{AllowFailure: true, NoCapture: true, Env: env, UID: &uid, GID: &gid, Background: true})
	}
	return nil
}
func (c *Controller) X11HostCommands() []string {
	return []string{"am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity", filepath.Join(c.Config.TermuxPrefix, "bin/pulseaudio") + " --start --exit-idle-time=-1", filepath.Join(c.Config.TermuxPrefix, "bin/termux-x11") + " :0 -ac &"}
}
func (c *Controller) Status(verbose bool) []map[string]string {
	table, _ := c.mountTable()
	rows := []map[string]string{}
	for _, s := range c.MountSpecs() {
		typ := s.FSType
		if s.Bind {
			typ = "bind"
			if s.ReadOnly {
				typ = "bind:ro"
			}
		}
		row := map[string]string{"source": s.Source, "target": s.Target, "type": typ, "mounted": "no"}
		if mounted(s, table) {
			row["mounted"] = "yes"
		}
		if verbose {
			if _, e := os.Stat(s.Target); e == nil {
				row["target_exists"] = "yes"
			} else {
				row["target_exists"] = "no"
			}
			if _, e := os.Stat(s.Source); e == nil {
				row["source_exists"] = "yes"
			} else {
				row["source_exists"] = "n/a"
			}
		}
		rows = append(rows, row)
	}
	return rows
}
func (c *Controller) Doctor() []map[string]string {
	which := func(x string) string { p, _ := exec.LookPath(x); return p }
	shell := c.resolvedShell()
	base := c.Config.ChrootBase()
	rootStatus := "warning"
	rootDetail := "sudo required"
	if sys.IsRoot() {
		rootStatus = "ok"
		rootDetail = "running as root"
	}
	rows := []map[string]string{{"check": "busybox", "status": map[bool]string{true: "ok", false: "missing"}[which("busybox") != ""], "detail": which("busybox")}, {"check": "chroot", "status": map[bool]string{true: "ok", false: "missing"}[which("chroot") != ""], "detail": which("chroot")}, {"check": "shell", "status": "missing", "detail": shell}, {"check": "chroot_base", "status": "missing", "detail": base}, {"check": "root", "status": rootStatus, "detail": rootDetail}}
	if _, e := os.Stat(filepath.Join(base, strings.TrimPrefix(shell, "/"))); e == nil {
		rows[2]["status"] = "ok"
	}
	if _, e := os.Stat(base); e == nil {
		rows[3]["status"] = "ok"
	}
	mountedCount := 0
	for _, r := range c.Status(false) {
		if r["mounted"] == "yes" {
			mountedCount++
		}
	}
	st := "warning"
	if mountedCount > 0 {
		st = "ok"
	}
	rows = append(rows, map[string]string{"check": "mounts", "status": st, "detail": fmt.Sprintf("%d/%d mounted", mountedCount, len(c.MountSpecs()))})
	return rows
}
