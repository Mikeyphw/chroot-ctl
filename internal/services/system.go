package services

import (
	"bufio"
	"chrootctl/internal/model"
	sys "chrootctl/internal/system"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var logLevelRE = regexp.MustCompile(`\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b`)
var catalogLinkRE = regexp.MustCompile(`(?i)\bapplied\s+(tool|addon)s?\s+([A-Za-z0-9][A-Za-z0-9._-]*)\b`)

type SystemService struct{ C *Container }

func (s *SystemService) defaultTarget(ctx context.Context) string {
	rows, _ := s.C.Registry.List(ctx)
	if len(rows) == 1 {
		return rows[0].Name
	}
	name := ""
	n := 0
	for _, r := range rows {
		if r.Installed {
			name = r.Name
			n++
		}
	}
	if n == 1 {
		return name
	}
	return ""
}
func (s *SystemService) Dashboard(ctx context.Context, target string, details bool, tail int) (model.DashboardSummary, error) {
	if target == "" {
		target = s.defaultTarget(ctx)
	}
	rows, e := s.C.Chroots().List(ctx)
	if e != nil {
		return model.DashboardSummary{}, e
	}
	d := model.DashboardSummary{Chroots: rows, StatusChecks: []model.CheckRow{}, DoctorChecks: []model.CheckRow{}}
	if target != "" {
		d.TargetName = &target
		d.StatusChecks, _ = s.Status(ctx, target, details)
		d.DoctorChecks, _ = s.Doctor(ctx, target)
		logs, _ := s.Logs(ctx, target, tail, false, "", false)
		d.Logs = &logs
	}
	return d, nil
}
func (s *SystemService) Status(ctx context.Context, name string, details bool) ([]model.CheckRow, error) {
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return nil, e
	}
	out := []model.CheckRow{}
	for _, r := range rt.Controller.Status(details) {
		target := r["target"]
		mounted := strings.EqualFold(r["mounted"], "yes")
		out = append(out, model.CheckRow{Check: target, Result: map[bool]string{true: "PASS", false: "WARN"}[mounted], Detail: target, Next: map[bool]string{true: "", false: "chrootctl mount"}[mounted]})
	}
	if details {
		if r, _ := s.C.Registry.Get(ctx, name); r != nil {
			result := "WARN"
			next := "chrootctl install --resume"
			if r.Installed {
				result = "PASS"
				next = "chrootctl status --details"
				if r.Phase == "finalize" {
					next = "chrootctl start"
				}
			}
			out = append(out, model.CheckRow{Check: "chroot", Result: result, Detail: fmt.Sprintf("phase=%s installed=%v", r.Phase, r.Installed), Next: next})
		}
	}
	return out, nil
}
func (s *SystemService) Doctor(ctx context.Context, name string) ([]model.CheckRow, error) {
	rt, e := s.C.RuntimeFor(name, "")
	if e != nil {
		return nil, e
	}
	out := []model.CheckRow{}
	for _, r := range rt.Controller.Doctor() {
		status := strings.ToLower(r["status"])
		result := "FAIL"
		if status == "ok" {
			result = "PASS"
		} else if status == "warning" || status == "warn" {
			result = "WARN"
		}
		next := "chrootctl doctor"
		if result == "PASS" {
			next = ""
		}
		if r["check"] == "mounts" && result != "PASS" {
			next = "chrootctl mount"
		}
		if r["check"] == "tty" && result != "PASS" {
			next = "chrootctl fix-tty"
		}
		out = append(out, model.CheckRow{Check: r["check"], Result: result, Detail: r["detail"], Next: next})
	}
	if r, _ := s.C.Registry.Get(ctx, name); r != nil {
		out = append(out, model.CheckRow{Check: "registry", Result: "PASS", Detail: fmt.Sprintf("phase=%s installed=%v", r.Phase, r.Installed)})
	}
	result := "WARN"
	next := "chrootctl logs --all"
	if exists(rt.Config.LogFile) {
		result = "PASS"
		next = ""
	}
	out = append(out, model.CheckRow{Check: "log_file", Result: result, Detail: rt.Config.LogFile, Next: next})
	return out, nil
}
func (s *SystemService) HostDoctor(ctx context.Context) []model.CheckRow {
	r := s.C.BaseConfig
	checks := []model.CheckRow{{Check: "backend_runtime", Result: "PASS", Detail: "Bundled backend runtime available."}}
	for _, cmd := range []struct {
		name  string
		block bool
	}{{"busybox", true}, {"tar", true}, {"zstd", true}, {"curl", false}, {"openssl", false}} {
		ok := sys.CommandExists(cmd.name)
		result := "PASS"
		if !ok {
			if cmd.block {
				result = "FAIL"
			} else {
				result = "WARN"
			}
		}
		next := ""
		if !ok {
			next = "Install " + cmd.name + " on the host."
		}
		checks = append(checks, model.CheckRow{Check: cmd.name, Result: result, Detail: map[bool]string{true: cmd.name + " available", false: cmd.name + " command not found on host."}[ok], Next: next})
	}
	rootResult := "WARN"
	next := "Use sudo/root for installs, mounts, and package operations."
	if sys.IsRoot() {
		rootResult = "PASS"
		next = ""
	}
	checks = append(checks, model.CheckRow{Check: "root_access", Result: rootResult, Detail: map[bool]string{true: "Root access is available.", false: "Current process is not running as root."}[sys.IsRoot()], Next: next})
	for name, path := range map[string]string{"chroot_root": r.ChrootRoot, "log_file_dir": filepath.Dir(r.LogFile), "database_dir": filepath.Dir(r.DatabasePath)} {
		ok := ensureWritable(path)
		result := "PASS"
		if !ok {
			result = "FAIL"
		}
		checks = append(checks, model.CheckRow{Check: name, Result: result, Detail: path, Next: map[bool]string{true: "", false: "Create or fix permissions for " + path + "."}[ok]})
	}
	return checks
}
func ensureWritable(path string) bool {
	if os.MkdirAll(path, 0755) != nil {
		return false
	}
	f, e := os.CreateTemp(path, ".chrootctl-write-*")
	if e != nil {
		return false
	}
	n := f.Name()
	f.Close()
	os.Remove(n)
	return true
}
func (s *SystemService) CrossArchRows(target, host string) []model.CheckRow {
	if host == "" {
		host = sys.HostArch()
	}
	native := target == host
	qemu := native
	for _, n := range sys.QEMUUserBinaryNames(target) {
		qemu = qemu || sys.CommandExists(n)
	}
	binfmt := native || sys.CanExecuteForeignArch(target)
	qres, bres := "WARN", "WARN"
	if qemu {
		qres = "PASS"
	}
	if binfmt {
		bres = "PASS"
	}
	return []model.CheckRow{{Check: target + "_qemu", Result: qres, Detail: map[bool]string{true: "qemu/native execution available", false: "qemu user binary not found"}[qemu]}, {Check: target + "_binfmt", Result: bres, Detail: map[bool]string{true: "binfmt/native execution available", false: "binfmt_misc is not enabled for this target"}[binfmt]}}
}
func (s *SystemService) CrossArchState() map[string]any {
	host := sys.HostArch()
	targets := []map[string]any{}
	for _, arch := range []string{"arm64", "amd64"} {
		native := arch == host
		qemu := native
		for _, n := range sys.QEMUUserBinaryNames(arch) {
			qemu = qemu || sys.CommandExists(n)
		}
		binfmt := native || sys.CanExecuteForeignArch(arch)
		mode := "extract-only"
		if native {
			mode = "native"
		} else if qemu && binfmt {
			mode = "foreign-ready"
		}
		targets = append(targets, map[string]any{"arch": arch, "native": native, "qemu_ready": qemu, "binfmt_ready": binfmt, "ready": native || (qemu && binfmt), "mode": mode})
	}
	return map[string]any{"host_arch": host, "targets": targets}
}
func (s *SystemService) ForeignArchAdvisories(ctx context.Context) []map[string]string {
	rows, _ := s.C.Chroots().List(ctx)
	host := sys.HostArch()
	out := []map[string]string{}
	for _, r := range rows {
		if r.Arch == "" || r.Arch == host {
			continue
		}
		mode := "deferred"
		if sys.CanExecuteForeignArch(r.Arch) {
			mode = "ready"
		}
		out = append(out, map[string]string{"name": r.Name, "arch": r.Arch, "phase": r.Phase, "installed": map[bool]string{true: "yes", false: "no"}[r.Installed], "mode": mode})
	}
	return out
}
func (s *SystemService) Logs(ctx context.Context, name string, tail int, showAll bool, level string, follow bool) (model.LogSnapshot, error) {
	cfg, e := s.C.ConfigFor(name, "")
	if e != nil {
		return model.LogSnapshot{}, e
	}
	lines := []string{}
	f, e := os.Open(cfg.LogFile)
	if e == nil {
		scan := bufio.NewScanner(f)
		for scan.Scan() {
			line := scan.Text()
			if level == "" || strings.Contains(strings.ToUpper(line), strings.ToUpper(level)) {
				lines = append(lines, line)
			}
		}
		f.Close()
	}
	if !showAll && tail > 0 && len(lines) > tail {
		lines = lines[len(lines)-tail:]
	}
	entries := []model.LogEntry{}
	for _, line := range lines {
		var lvl *string
		if m := logLevelRE.FindString(line); m != "" {
			x := m
			lvl = &x
		}
		links := []model.LogLink{}
		for _, m := range catalogLinkRE.FindAllStringSubmatch(line, -1) {
			href := "/tools/" + m[2]
			if strings.EqualFold(m[1], "addon") {
				href = "/addons/" + m[2]
			}
			links = append(links, model.LogLink{Label: m[1] + " · " + m[2], Href: href})
		}
		entries = append(entries, model.LogEntry{Line: line, Level: lvl, Links: links})
	}
	var lp *string
	if level != "" {
		x := strings.ToUpper(level)
		lp = &x
	}
	var target *string
	related := []model.LogLink{}
	if name != "" {
		target = &name
		related = []model.LogLink{{Label: "Chroot · " + name, Href: "/chroots/" + name}, {Label: "Users · " + name, Href: "/chroots/" + name + "/users"}, {Label: "Status · " + name, Href: "/status?name=" + name}, {Label: "Doctor · " + name, Href: "/doctor?name=" + name}}
	}
	return model.LogSnapshot{LogFile: cfg.LogFile, Level: lp, Lines: lines, Follow: follow, TargetName: target, Entries: entries, RelatedLinks: related}, nil
}

type DoctorService struct{ C *Container }

func (s *DoctorService) HostReadiness(ctx context.Context) map[string]any {
	rows := s.C.System().HostDoctor(ctx)
	summary := map[string]int{"pass": 0, "warn": 0, "fail": 0}
	blockers := []model.CheckRow{}
	for _, r := range rows {
		summary[strings.ToLower(r.Result)]++
		if r.Result == "FAIL" {
			blockers = append(blockers, r)
		}
	}
	return map[string]any{"host_arch": sys.HostArch(), "checks": rows, "summary": summary, "advisories": s.C.System().ForeignArchAdvisories(ctx), "blockers": blockers}
}
func (s *DoctorService) CrossArchReadiness() map[string]any { return s.C.System().CrossArchState() }
