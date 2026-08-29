package services

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
)

type ServiceUnit struct {
	Name, Path, Description, Chroot, User, ExecStart, ExecStop, WorkingDirectory, Restart string
	Environment                                                                           map[string]string
	X11, Root                                                                             bool
	WantedBy, After, Requires                                                             []string
}
type UnitService struct{ C *Container }

func normalizeUnitName(name string) string {
	name = strings.TrimSpace(name)
	if !strings.HasSuffix(name, ".service") {
		name += ".service"
	}
	return name
}
func splitWords(v string) []string {
	if strings.TrimSpace(v) == "" {
		return nil
	}
	return strings.Fields(v)
}
func parseBool(v string) bool { b, _ := strconv.ParseBool(strings.TrimSpace(v)); return b }
func loadUnit(path string) (ServiceUnit, error) {
	f, e := os.Open(path)
	if e != nil {
		return ServiceUnit{}, e
	}
	defer f.Close()
	u := ServiceUnit{Name: filepath.Base(path), Path: path, Environment: map[string]string{}, Restart: "no"}
	section := ""
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, ";") {
			continue
		}
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			section = strings.Trim(line, "[]")
			continue
		}
		p := strings.SplitN(line, "=", 2)
		if len(p) != 2 {
			continue
		}
		k, v := strings.TrimSpace(p[0]), strings.TrimSpace(p[1])
		switch section + "." + k {
		case "Unit.Description":
			u.Description = v
		case "Unit.After":
			u.After = splitWords(v)
		case "Unit.Requires":
			u.Requires = splitWords(v)
		case "Service.Chroot":
			u.Chroot = v
		case "Service.User":
			u.User = v
		case "Service.ExecStart":
			u.ExecStart = v
		case "Service.ExecStop":
			u.ExecStop = v
		case "Service.WorkingDirectory":
			u.WorkingDirectory = v
		case "Service.X11":
			u.X11 = parseBool(v)
		case "Service.Root":
			u.Root = parseBool(v)
		case "Service.Restart":
			u.Restart = v
		case "Service.Environment":
			for _, part := range strings.Fields(v) {
				kv := strings.SplitN(part, "=", 2)
				if len(kv) == 2 {
					u.Environment[kv[0]] = strings.Trim(kv[1], "\"'")
				}
			}
		case "Install.WantedBy":
			u.WantedBy = splitWords(v)
		}
	}
	if e = sc.Err(); e != nil {
		return ServiceUnit{}, e
	}
	if u.ExecStart == "" {
		return ServiceUnit{}, fmt.Errorf("service %s is missing ExecStart", u.Name)
	}
	if u.Chroot != "" {
		if _, e := validation.ChrootName(u.Chroot); e != nil {
			return ServiceUnit{}, e
		}
	}
	return u, nil
}
func (s *UnitService) units() (map[string]ServiceUnit, error) {
	out := map[string]ServiceUnit{}
	for _, dir := range s.C.BaseConfig.ServiceDirs {
		entries, e := os.ReadDir(dir)
		if os.IsNotExist(e) {
			continue
		}
		if e != nil {
			return nil, e
		}
		for _, ent := range entries {
			if ent.IsDir() || !strings.HasSuffix(ent.Name(), ".service") {
				continue
			}
			p := filepath.Join(dir, ent.Name())
			st, e := os.Lstat(p)
			if e != nil || !st.Mode().IsRegular() {
				continue
			}
			u, e := loadUnit(p)
			if e != nil {
				return nil, e
			}
			out[u.Name] = u
		}
	}
	return out, nil
}
func (s *UnitService) get(name string) (ServiceUnit, error) {
	name = normalizeUnitName(name)
	units, e := s.units()
	if e != nil {
		return ServiceUnit{}, e
	}
	u, ok := units[name]
	if !ok {
		return ServiceUnit{}, fmt.Errorf("unknown service unit: %s", name)
	}
	return u, nil
}
func (s *UnitService) bound(u ServiceUnit, requested string) (string, error) {
	name := requested
	if name == "" {
		name = u.Chroot
	}
	if name == "" {
		return "", fmt.Errorf("service %s is not bound to a chroot", u.Name)
	}
	return validation.ChrootName(name)
}
func (s *UnitService) statePrefix(chroot, unit string) string {
	return filepath.Join(s.C.BaseConfig.ServiceStateDir, safeArtifactName(chroot)+"-"+safeArtifactName(unit))
}
func (s *UnitService) logPath(chroot, unit string) string {
	return filepath.Join(s.C.BaseConfig.ServiceLogDir, safeArtifactName(chroot)+"-"+safeArtifactName(unit)+".log")
}
func readIdentity(path string) *sys.ProcessIdentity {
	b, e := os.ReadFile(path)
	if e != nil {
		return nil
	}
	var id sys.ProcessIdentity
	if json.Unmarshal(b, &id) != nil {
		return nil
	}
	return &id
}
func writeIdentity(path string, id *sys.ProcessIdentity) error {
	if id == nil {
		return fmt.Errorf("process identity unavailable")
	}
	if e := os.MkdirAll(filepath.Dir(path), 0755); e != nil {
		return e
	}
	b, _ := json.Marshal(id)
	return os.WriteFile(path, b, 0600)
}
func (s *UnitService) IsEnabled(chroot, unit, target string) bool {
	if target == "" {
		target = "boot.target"
	}
	p := filepath.Join(s.C.BaseConfig.ServiceStateDir, "targets", safeArtifactName(target)+".wants", safeArtifactName(chroot)+"-"+safeArtifactName(unit)+".enabled")
	return exists(p)
}
func (s *UnitService) List(ctx context.Context) ([]map[string]string, error) {
	units, e := s.units()
	if e != nil {
		return nil, e
	}
	names := make([]string, 0, len(units))
	for n := range units {
		names = append(names, n)
	}
	sort.Strings(names)
	out := []map[string]string{}
	for _, n := range names {
		u := units[n]
		ch := u.Chroot
		st, _ := s.Status(ctx, n, ch)
		out = append(out, map[string]string{"service": n, "chroot": ch, "enabled": map[bool]string{true: "yes", false: "no"}[s.IsEnabled(ch, n, "boot.target")], "boot": map[bool]string{true: "yes", false: "no"}[s.IsEnabled(ch, n, "boot.target")], "wanted_by": strings.Join(u.WantedBy, ","), "after": strings.Join(u.After, ","), "requires": strings.Join(u.Requires, ","), "status": fmt.Sprint(st["status"]), "description": u.Description})
	}
	return out, nil
}
func (s *UnitService) Status(ctx context.Context, name, chroot string) (map[string]any, error) {
	u, e := s.get(name)
	if e != nil {
		return nil, e
	}
	ch, e := s.bound(u, chroot)
	if e != nil {
		return nil, e
	}
	prefix := s.statePrefix(ch, u.Name)
	id := readIdentity(prefix + ".identity.json")
	status := "stopped"
	pid := 0
	if id != nil && sys.ProcessIdentityMatches(*id) {
		status = "running"
		pid = id.PID
	} else if id != nil {
		_ = os.Remove(prefix + ".identity.json")
		_ = os.Remove(prefix + ".pid")
	}
	return map[string]any{"service": u.Name, "chroot": ch, "status": status, "pid": pid, "enabled": s.IsEnabled(ch, u.Name, "boot.target"), "log_file": s.logPath(ch, u.Name)}, nil
}
func (s *UnitService) Start(ctx context.Context, name, chroot string, foreground bool) (map[string]any, error) {
	u, e := s.get(name)
	if e != nil {
		return nil, e
	}
	ch, e := s.bound(u, chroot)
	if e != nil {
		return nil, e
	}
	if st, _ := s.Status(ctx, name, ch); st["status"] == "running" {
		return st, nil
	}
	rt, e := s.C.RuntimeFor(ch, u.User)
	if e != nil {
		return nil, e
	}
	if e = rt.Controller.Prepare(ctx, u.X11); e != nil {
		return nil, e
	}
	rootUser := u.Root || strings.EqualFold(u.User, "root")
	argv, env, e := rt.Controller.ServiceInvocation(rootUser, u.ExecStart, u.X11, u.User)
	if e != nil {
		return nil, e
	}
	for k, v := range u.Environment {
		env[k] = v
	}
	if e = os.MkdirAll(s.C.BaseConfig.ServiceLogDir, 0755); e != nil {
		return nil, e
	}
	log := s.logPath(ch, u.Name)
	pid, e := rt.Runner.Spawn(argv, sys.SpawnOptions{Env: env, OutputPath: log, Append: true})
	if e != nil {
		return nil, e
	}
	id := sys.CaptureProcessIdentity(pid)
	prefix := s.statePrefix(ch, u.Name)
	if e = writeIdentity(prefix+".identity.json", id); e != nil {
		return nil, e
	}
	_ = os.WriteFile(prefix+".pid", []byte(strconv.Itoa(pid)+"\n"), 0600)
	return map[string]any{"service": u.Name, "chroot": ch, "status": map[bool]string{true: "foreground", false: "running"}[foreground], "pid": pid, "log_file": log}, nil
}
func (s *UnitService) Stop(ctx context.Context, name, chroot string) (map[string]any, error) {
	u, e := s.get(name)
	if e != nil {
		return nil, e
	}
	ch, e := s.bound(u, chroot)
	if e != nil {
		return nil, e
	}
	prefix := s.statePrefix(ch, u.Name)
	id := readIdentity(prefix + ".identity.json")
	log := s.logPath(ch, u.Name)
	if id == nil || !sys.ProcessIdentityMatches(*id) {
		_ = os.Remove(prefix + ".identity.json")
		_ = os.Remove(prefix + ".pid")
		return map[string]any{"service": u.Name, "chroot": ch, "status": "stopped", "detail": "no verified process identity", "log_file": log}, nil
	}
	if u.ExecStop != "" {
		rt, _ := s.C.RuntimeFor(ch, u.User)
		rootUser := u.Root || strings.EqualFold(u.User, "root")
		argv, env, _ := rt.Controller.ServiceInvocation(rootUser, u.ExecStop, u.X11, u.User)
		_, _ = rt.Runner.Run(ctx, argv, sys.RunOptions{Env: env, AllowFailure: true, MaxCaptureBytes: 128 * 1024})
	}
	_ = sys.SignalProcessIdentity(*id, syscall.SIGTERM)
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) && sys.ProcessIdentityMatches(*id) {
		time.Sleep(100 * time.Millisecond)
	}
	if sys.ProcessIdentityMatches(*id) {
		_ = sys.SignalProcessIdentity(*id, syscall.SIGKILL)
	}
	_ = os.Remove(prefix + ".identity.json")
	_ = os.Remove(prefix + ".pid")
	return map[string]any{"service": u.Name, "chroot": ch, "status": "stopped", "pid": id.PID, "log_file": log}, nil
}
func (s *UnitService) Restart(ctx context.Context, name, chroot string) (map[string]any, error) {
	st, e := s.Stop(ctx, name, chroot)
	if e != nil {
		return nil, e
	}
	start, e := s.Start(ctx, name, chroot, false)
	return map[string]any{"stopped": st, "started": start}, e
}
func (s *UnitService) Logs(ctx context.Context, name, chroot string, tail int) (map[string]any, error) {
	u, e := s.get(name)
	if e != nil {
		return nil, e
	}
	ch, e := s.bound(u, chroot)
	if e != nil {
		return nil, e
	}
	p := s.logPath(ch, u.Name)
	b, _ := os.ReadFile(p)
	lines := strings.Split(strings.TrimSuffix(string(b), "\n"), "\n")
	if len(lines) == 1 && lines[0] == "" {
		lines = nil
	}
	if tail > 0 && len(lines) > tail {
		lines = lines[len(lines)-tail:]
	}
	return map[string]any{"service": u.Name, "chroot": ch, "log_file": p, "lines": lines}, nil
}
func (s *UnitService) Enable(ctx context.Context, name, chroot, target string) (map[string]any, error) {
	u, e := s.get(name)
	if e != nil {
		return nil, e
	}
	ch, e := s.bound(u, chroot)
	if e != nil {
		return nil, e
	}
	if target == "" {
		target = "boot.target"
	}
	dir := filepath.Join(s.C.BaseConfig.ServiceStateDir, "targets", safeArtifactName(target)+".wants")
	if e = os.MkdirAll(dir, 0755); e != nil {
		return nil, e
	}
	p := filepath.Join(dir, safeArtifactName(ch)+"-"+safeArtifactName(u.Name)+".enabled")
	if e = os.WriteFile(p, []byte(u.Name+"\n"), 0600); e != nil {
		return nil, e
	}
	return map[string]any{"service": u.Name, "chroot": ch, "enabled": true, "target": target}, nil
}
func (s *UnitService) Disable(ctx context.Context, name, chroot, target string) (map[string]any, error) {
	u, e := s.get(name)
	if e != nil {
		return nil, e
	}
	ch, e := s.bound(u, chroot)
	if e != nil {
		return nil, e
	}
	if target == "" {
		target = "boot.target"
	}
	p := filepath.Join(s.C.BaseConfig.ServiceStateDir, "targets", safeArtifactName(target)+".wants", safeArtifactName(ch)+"-"+safeArtifactName(u.Name)+".enabled")
	_ = os.Remove(p)
	return map[string]any{"service": u.Name, "chroot": ch, "enabled": false, "target": target}, nil
}
