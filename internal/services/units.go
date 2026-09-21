package services

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"chrootctl/internal/logging"
	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
)

type ServiceUnit struct {
	Name, Path, Description, Chroot, User, ExecStart, ExecStop, WorkingDirectory, Restart string
	RestartSec                                                                            int
	Environment                                                                           map[string]string
	X11, Root, EnabledByDefault                                                           bool
	WantedBy, After, Requires                                                             []string
}
type UnitService struct{ C *Container }

var serviceUnitNameRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.@-]*\.service$`)

func normalizeUnitName(name string) string {
	name = strings.TrimSpace(name)
	if !strings.HasSuffix(name, ".service") {
		name += ".service"
	}
	return name
}
func validateUnitName(name string) error {
	if !serviceUnitNameRE.MatchString(name) {
		return fmt.Errorf("invalid service unit name %q", name)
	}
	return nil
}
func splitWords(v string) []string {
	if strings.TrimSpace(v) == "" {
		return nil
	}
	return strings.Fields(v)
}
func parseBoolStrict(v, field string) (bool, error) {
	b, err := strconv.ParseBool(strings.TrimSpace(v))
	if err != nil {
		return false, fmt.Errorf("%s must be a boolean, got %q", field, v)
	}
	return b, nil
}
func splitQuotedFields(v string) ([]string, error) {
	out := []string{}
	var b strings.Builder
	var quote rune
	escaped := false
	flush := func() {
		if b.Len() > 0 {
			out = append(out, b.String())
			b.Reset()
		}
	}
	for _, r := range v {
		if escaped {
			b.WriteRune(r)
			escaped = false
			continue
		}
		if r == '\\' {
			escaped = true
			continue
		}
		if quote != 0 {
			if r == quote {
				quote = 0
			} else {
				b.WriteRune(r)
			}
			continue
		}
		if r == '\'' || r == '"' {
			quote = r
			continue
		}
		if r == ' ' || r == '\t' {
			flush()
			continue
		}
		b.WriteRune(r)
	}
	if escaped {
		b.WriteRune('\\')
	}
	if quote != 0 {
		return nil, errors.New("unterminated quote in Environment=")
	}
	flush()
	return out, nil
}
func loadUnit(path string) (ServiceUnit, error) {
	f, e := os.Open(path)
	if e != nil {
		return ServiceUnit{}, e
	}
	defer f.Close()
	u := ServiceUnit{Name: filepath.Base(path), Path: path, Environment: map[string]string{}, Restart: "no", RestartSec: 1}
	if err := validateUnitName(u.Name); err != nil {
		return ServiceUnit{}, err
	}
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
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			return ServiceUnit{}, fmt.Errorf("service %s has malformed line %q", u.Name, line)
		}
		k, v := strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
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
			b, err := parseBoolStrict(v, "Service.X11")
			if err != nil {
				return ServiceUnit{}, err
			}
			u.X11 = b
		case "Service.Root":
			b, err := parseBoolStrict(v, "Service.Root")
			if err != nil {
				return ServiceUnit{}, err
			}
			u.Root = b
		case "Service.Restart":
			r := strings.ToLower(strings.TrimSpace(v))
			if r != "no" && r != "always" && r != "on-failure" {
				return ServiceUnit{}, fmt.Errorf("service %s has invalid Restart %q", u.Name, v)
			}
			u.Restart = r
		case "Service.RestartSec":
			n, err := strconv.Atoi(strings.TrimSuffix(strings.TrimSpace(v), "s"))
			if err != nil || n < 0 {
				return ServiceUnit{}, fmt.Errorf("service %s has invalid RestartSec %q", u.Name, v)
			}
			u.RestartSec = n
		case "Service.Environment":
			fields, err := splitQuotedFields(v)
			if err != nil {
				return ServiceUnit{}, fmt.Errorf("service %s: %w", u.Name, err)
			}
			for _, part := range fields {
				kv := strings.SplitN(part, "=", 2)
				if len(kv) != 2 || kv[0] == "" {
					return ServiceUnit{}, fmt.Errorf("service %s has invalid Environment token %q", u.Name, part)
				}
				u.Environment[kv[0]] = kv[1]
			}
		case "Install.WantedBy":
			u.WantedBy = splitWords(v)
		case "Install.Enabled":
			b, err := parseBoolStrict(v, "Install.Enabled")
			if err != nil {
				return ServiceUnit{}, err
			}
			u.EnabledByDefault = b
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

func trustedUnitPath(path string) error {
	st, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !st.Mode().IsRegular() {
		return fmt.Errorf("service unit %s must be a regular non-symlink file", path)
	}
	if !sys.IsRoot() {
		return nil
	}
	stat, ok := st.Sys().(*syscall.Stat_t)
	if !ok {
		return fmt.Errorf("service unit %s ownership unavailable", path)
	}
	if stat.Uid != 0 {
		return fmt.Errorf("service unit %s must be root-owned", path)
	}
	if st.Mode().Perm()&0o022 != 0 {
		return fmt.Errorf("service unit %s must not be group/world writable", path)
	}
	dir := filepath.Dir(path)
	dst, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	ds, ok := dst.Sys().(*syscall.Stat_t)
	if !ok || ds.Uid != 0 || dst.Mode().Perm()&0o022 != 0 {
		return fmt.Errorf("service directory %s is not a trusted root-owned directory", dir)
	}
	return nil
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
			if err := trustedUnitPath(p); err != nil {
				return nil, err
			}
			u, e := loadUnit(p)
			if e != nil {
				return nil, e
			}
			if _, dup := out[u.Name]; dup {
				return nil, fmt.Errorf("duplicate service unit %s", u.Name)
			}
			out[u.Name] = u
		}
	}
	return out, nil
}
func (s *UnitService) get(name string) (ServiceUnit, error) {
	name = normalizeUnitName(name)
	if err := validateUnitName(name); err != nil {
		return ServiceUnit{}, err
	}
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
	if requested != "" && u.Chroot != "" && requested != u.Chroot {
		return "", fmt.Errorf("service %s is bound to chroot %s, not %s", u.Name, u.Chroot, requested)
	}
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

type serviceRuntimeState struct {
	Status    string `json:"status"`
	Detail    string `json:"detail,omitempty"`
	UpdatedAt int64  `json:"updated_at"`
}

func (s *UnitService) statePath(chroot, unit string) string {
	return s.statePrefix(chroot, unit) + ".state.json"
}
func (s *UnitService) readState(chroot, unit string) serviceRuntimeState {
	var st serviceRuntimeState
	b, err := os.ReadFile(s.statePath(chroot, unit))
	if err == nil {
		_ = json.Unmarshal(b, &st)
	}
	return st
}
func (s *UnitService) writeState(chroot, unit, status, detail string) error {
	if s.C.DryRun {
		return nil
	}
	p := s.statePath(chroot, unit)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	b, err := json.Marshal(serviceRuntimeState{Status: status, Detail: detail, UpdatedAt: time.Now().Unix()})
	if err != nil {
		return err
	}
	return os.WriteFile(p, b, 0o600)
}
func wantedBy(u ServiceUnit, target string) bool {
	for _, v := range u.WantedBy {
		if normalizeUnitName(v) == normalizeUnitName(target) || v == target {
			return true
		}
	}
	return false
}
func (s *UnitService) EffectiveEnabled(u ServiceUnit, chroot, target string) bool {
	return s.IsEnabled(chroot, u.Name, target) || (u.EnabledByDefault && wantedBy(u, target))
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
		st, err := s.Status(ctx, n, ch)
		if err != nil {
			return nil, fmt.Errorf("service %s status: %w", n, err)
		}
		out = append(out, map[string]string{"service": n, "chroot": ch, "enabled": map[bool]string{true: "yes", false: "no"}[s.EffectiveEnabled(u, ch, "boot.target")], "boot": map[bool]string{true: "yes", false: "no"}[wantedBy(u, "boot.target")], "wanted_by": strings.Join(u.WantedBy, ","), "after": strings.Join(u.After, ","), "requires": strings.Join(u.Requires, ","), "status": fmt.Sprint(st["status"]), "description": u.Description})
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
	runtime := s.readState(ch, u.Name)
	status := "stopped"
	pid := 0
	detail := runtime.Detail
	if id != nil && sys.ProcessIdentityMatches(*id) {
		status = "running"
		pid = id.PID
	} else if id != nil {
		status = "stale"
		detail = "recorded process identity no longer matches a live process"
	} else if runtime.Status == "failed" {
		status = "failed"
	} else if runtime.Status == "running" || runtime.Status == "starting" {
		status = "stale"
		detail = "runtime state claims active service but process identity is missing"
	}
	return map[string]any{"service": u.Name, "chroot": ch, "status": status, "pid": pid, "enabled": s.EffectiveEnabled(u, ch, "boot.target"), "boot": wantedBy(u, "boot.target"), "wanted_by": u.WantedBy, "log_file": s.logPath(ch, u.Name), "detail": detail}, nil
}
func serviceShellQuote(v string) string {
	return "'" + strings.ReplaceAll(v, "'", "'\\''") + "'"
}

func serviceStartCommand(u ServiceUnit) string {
	cmd := u.ExecStart
	if u.WorkingDirectory != "" {
		cmd = "cd -- " + serviceShellQuote(u.WorkingDirectory) + " && " + cmd
	}
	switch strings.ToLower(strings.TrimSpace(u.Restart)) {
	case "always":
		return fmt.Sprintf("while :; do ( %s ); sleep %d; done", cmd, u.RestartSec)
	case "on-failure":
		return fmt.Sprintf("while :; do ( %s ); rc=$?; [ \"$rc\" -eq 0 ] && exit 0; sleep %d; done", cmd, u.RestartSec)
	default:
		return cmd
	}
}

type bootUnitRef struct {
	Name   string
	Chroot string
}

func buildBootLayers(units map[string]ServiceUnit, enabled func(chroot, unit string) bool) ([][]bootUnitRef, error) {
	selected := map[string]bool{}
	var include func(string) error
	include = func(name string) error {
		name = normalizeUnitName(name)
		if selected[name] {
			return nil
		}
		u, ok := units[name]
		if !ok {
			if name == "network-online.service" || name == "network.target.service" {
				return nil
			}
			return fmt.Errorf("required service %s is neither a managed unit nor a supported host dependency", name)
		}
		if u.Chroot == "" {
			return fmt.Errorf("boot service %s is not bound to a chroot", name)
		}
		selected[name] = true
		for _, dep := range u.Requires {
			if err := include(dep); err != nil {
				return err
			}
		}
		return nil
	}
	for name, u := range units {
		if u.Chroot != "" && enabled(u.Chroot, name) {
			if err := include(name); err != nil {
				return nil, err
			}
		}
	}
	indegree := map[string]int{}
	edges := map[string]map[string]bool{}
	for name := range selected {
		indegree[name] = 0
	}
	for name := range selected {
		u := units[name]
		deps := append(append([]string(nil), u.Requires...), u.After...)
		for _, raw := range deps {
			dep := normalizeUnitName(raw)
			if !selected[dep] || dep == name {
				continue
			}
			if edges[dep] == nil {
				edges[dep] = map[string]bool{}
			}
			if !edges[dep][name] {
				edges[dep][name] = true
				indegree[name]++
			}
		}
	}
	remaining := len(selected)
	layers := [][]bootUnitRef{}
	for remaining > 0 {
		ready := []string{}
		for name, degree := range indegree {
			if degree == 0 {
				ready = append(ready, name)
			}
		}
		if len(ready) == 0 {
			return nil, fmt.Errorf("service dependency cycle detected among %d boot unit(s)", remaining)
		}
		sort.Strings(ready)
		layer := make([]bootUnitRef, 0, len(ready))
		for _, name := range ready {
			layer = append(layer, bootUnitRef{Name: name, Chroot: units[name].Chroot})
			delete(indegree, name)
			remaining--
		}
		for _, name := range ready {
			for child := range edges[name] {
				indegree[child]--
			}
		}
		layers = append(layers, layer)
	}
	return layers, nil
}

func (s *UnitService) Boot(ctx context.Context, target string, parallel bool) (map[string]any, error) {
	if target == "" {
		target = "boot.target"
	}
	units, err := s.units()
	if err != nil {
		return nil, err
	}
	layers, err := buildBootLayers(units, func(chroot, unit string) bool {
		u := units[normalizeUnitName(unit)]
		return s.EffectiveEnabled(u, chroot, target)
	})
	if err != nil {
		return nil, err
	}
	started := []map[string]any{}
	for _, layer := range layers {
		if !parallel || len(layer) < 2 {
			for _, ref := range layer {
				row, e := s.Start(ctx, ref.Name, ref.Chroot, false)
				if e != nil {
					return map[string]any{"target": target, "parallel": parallel, "started": started, "count": len(started), "failed_service": ref.Name, "failed_result": row}, e
				}
				started = append(started, row)
			}
			continue
		}
		type result struct {
			row map[string]any
			err error
		}
		ch := make(chan result, len(layer))
		var wg sync.WaitGroup
		for _, ref := range layer {
			ref := ref
			wg.Add(1)
			go func() {
				defer wg.Done()
				row, e := s.Start(ctx, ref.Name, ref.Chroot, false)
				ch <- result{row: row, err: e}
			}()
		}
		wg.Wait()
		close(ch)
		rows := []map[string]any{}
		var firstErr error
		for r := range ch {
			if r.err != nil {
				if firstErr == nil {
					firstErr = r.err
				}
				continue
			}
			rows = append(rows, r.row)
		}
		if firstErr != nil {
			started = append(started, rows...)
			return map[string]any{"target": target, "parallel": parallel, "started": started, "count": len(started)}, firstErr
		}
		sort.Slice(rows, func(i, j int) bool { return fmt.Sprint(rows[i]["service"]) < fmt.Sprint(rows[j]["service"]) })
		started = append(started, rows...)
	}
	plan := make([][]string, 0, len(layers))
	for _, layer := range layers {
		names := make([]string, 0, len(layer))
		for _, ref := range layer {
			names = append(names, ref.Name)
		}
		plan = append(plan, names)
	}
	return map[string]any{"target": target, "parallel": parallel, "layers": plan, "started": started, "count": len(started)}, nil
}

func serviceEnvKeys(env map[string]string) string {
	keys := make([]string, 0, len(env))
	for k := range env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return strings.Join(keys, ",")
}

const maxServiceLogBytes int64 = 4 * 1024 * 1024

func rotateServiceLogIfNeeded(path string) error {
	return logging.RotateFileIfNeeded(path, maxServiceLogBytes, logging.MaxLogBackups)
}

func appendServiceLifecycle(path string, lines ...string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	if err := rotateServiceLogIfNeeded(path); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	for _, line := range lines {
		if _, err = fmt.Fprintf(f, "%s chrootctl-service: %s\n", time.Now().UTC().Format(time.RFC3339), line); err != nil {
			return err
		}
	}
	return f.Sync()
}
func cleanupServiceIdentity(prefix string) error {
	var first error
	for _, p := range []string{prefix + ".identity.json", prefix + ".pid"} {
		if err := os.Remove(p); err != nil && !os.IsNotExist(err) && first == nil {
			first = err
		}
	}
	return first
}

func (s *UnitService) Start(ctx context.Context, name, chroot string, foreground bool) (result map[string]any, err error) {
	defer func() {
		if s.C.DryRun {
			return
		}
		auditErr := s.C.Audit().RecordMutation(context.WithoutCancel(ctx), "service.start", chroot+":"+name, err, map[string]string{"foreground": strconv.FormatBool(foreground)})
		err = errors.Join(err, auditErr)
	}()
	u, e := s.get(name)
	if e != nil {
		return nil, e
	}
	ch, e := s.bound(u, chroot)
	if e != nil {
		return nil, e
	}
	if st, err := s.Status(ctx, name, ch); err == nil && st["status"] == "running" {
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
	argv, env, e := rt.Controller.ServiceInvocation(rootUser, serviceStartCommand(u), u.X11, u.User)
	if e != nil {
		return nil, e
	}
	for k, v := range u.Environment {
		env[k] = v
	}
	log := s.logPath(ch, u.Name)
	if !s.C.DryRun {
		if e = appendServiceLifecycle(log, "starting service="+u.Name+" chroot="+ch+" user="+u.User+" cwd="+u.WorkingDirectory, "environment_keys="+serviceEnvKeys(u.Environment)); e != nil {
			return nil, e
		}
		preflight := `printf '%s\n' '--- chrootctl service preflight ---'; id; groups; printf 'HOME=%s\n' "$HOME"; pwd; { ls -la "$HOME" 2>&1 | head -20; }`
		preArgv, preEnv, preErr := rt.Controller.ServiceInvocation(rootUser, preflight, u.X11, u.User)
		if preErr != nil {
			return nil, preErr
		}
		for k, v := range u.Environment {
			preEnv[k] = v
		}
		preResult, preErr := rt.Runner.Run(ctx, preArgv, sys.RunOptions{Env: preEnv, ChrootEnv: true, MaxCaptureBytes: 64 * 1024})
		if preErr != nil || preResult.ReturnCode != 0 {
			if preErr == nil {
				preErr = fmt.Errorf("service preflight exited %d: %s", preResult.ReturnCode, strings.TrimSpace(preResult.Stderr))
			}
			_ = s.writeState(ch, u.Name, "failed", preErr.Error())
			return nil, preErr
		}
		if text := strings.TrimSpace(preResult.Stdout); text != "" {
			if e = appendServiceLifecycle(log, strings.ReplaceAll(text, "\n", " | ")); e != nil {
				return nil, e
			}
		}
	}
	if foreground {
		res, runErr := rt.Runner.RunAttached(ctx, argv, sys.RunOptions{Env: env, ChrootEnv: true})
		status := "exited"
		if runErr != nil {
			status = "failed"
		}
		_ = s.writeState(ch, u.Name, status, fmt.Sprintf("exit_code=%d", res.ReturnCode))
		return map[string]any{"service": u.Name, "chroot": ch, "status": status, "exit_code": res.ReturnCode, "log_file": log, "foreground": true}, runErr
	}
	if s.C.DryRun || rt.Runner.DryRun {
		return map[string]any{"service": u.Name, "chroot": ch, "status": "dry-run", "pid": 0, "log_file": log, "dry_run": true}, nil
	}
	if e = s.writeState(ch, u.Name, "starting", ""); e != nil {
		return nil, e
	}
	pid, e := rt.Runner.Spawn(argv, sys.SpawnOptions{Env: env, ChrootEnv: true, OutputPath: log, Append: true})
	if e != nil {
		_ = s.writeState(ch, u.Name, "failed", e.Error())
		return nil, e
	}
	id := sys.CaptureProcessIdentity(pid)
	prefix := s.statePrefix(ch, u.Name)
	failAfterSpawn := func(cause error) (map[string]any, error) {
		if id != nil {
			_ = sys.TerminateProcessIdentity(*id, 2*time.Second)
		}
		_ = cleanupServiceIdentity(prefix)
		_ = s.writeState(ch, u.Name, "failed", cause.Error())
		return map[string]any{"service": u.Name, "chroot": ch, "status": "failed", "pid": pid, "log_file": log}, cause
	}
	if id == nil {
		return failAfterSpawn(errors.New("spawned service process identity could not be captured"))
	}
	if e = writeIdentity(prefix+".identity.json", id); e != nil {
		return failAfterSpawn(fmt.Errorf("persist service identity: %w", e))
	}
	if e = os.WriteFile(prefix+".pid", []byte(strconv.Itoa(pid)+"\n"), 0o600); e != nil {
		return failAfterSpawn(fmt.Errorf("persist service pid: %w", e))
	}
	time.Sleep(200 * time.Millisecond)
	if !sys.ProcessIdentityMatches(*id) {
		return failAfterSpawn(errors.New("service process exited during startup confirmation"))
	}
	if e = s.writeState(ch, u.Name, "running", ""); e != nil {
		return failAfterSpawn(fmt.Errorf("persist running service state: %w", e))
	}
	_ = appendServiceLifecycle(log, "running pid="+strconv.Itoa(pid))
	return map[string]any{"service": u.Name, "chroot": ch, "status": "running", "pid": pid, "log_file": log}, nil
}
func (s *UnitService) Stop(ctx context.Context, name, chroot string) (result map[string]any, err error) {
	defer func() {
		if s.C.DryRun {
			return
		}
		auditErr := s.C.Audit().RecordMutation(context.WithoutCancel(ctx), "service.stop", chroot+":"+name, err, nil)
		err = errors.Join(err, auditErr)
	}()
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
	if id == nil {
		st := s.readState(ch, u.Name)
		if st.Status == "running" || st.Status == "starting" || st.Status == "stale" {
			_ = s.writeState(ch, u.Name, "stale", "active state has no verifiable process identity")
			return map[string]any{"service": u.Name, "chroot": ch, "status": "stale", "log_file": log}, errors.New("service process identity is missing; refusing to report stopped")
		}
		return map[string]any{"service": u.Name, "chroot": ch, "status": "stopped", "detail": "no recorded process identity", "log_file": log}, nil
	}
	if !sys.ProcessIdentityMatches(*id) {
		_ = s.writeState(ch, u.Name, "stale", "recorded process identity no longer matches")
		return map[string]any{"service": u.Name, "chroot": ch, "status": "stale", "pid": id.PID, "log_file": log}, errors.New("service process identity is stale; refusing to discard recovery evidence")
	}
	_ = appendServiceLifecycle(log, "stopping pid="+strconv.Itoa(id.PID))
	var stopHookErr error
	if u.ExecStop != "" {
		rt, err := s.C.RuntimeFor(ch, u.User)
		if err != nil {
			stopHookErr = err
		} else {
			rootUser := u.Root || strings.EqualFold(u.User, "root")
			argv, env, err := rt.Controller.ServiceInvocation(rootUser, u.ExecStop, u.X11, u.User)
			if err != nil {
				stopHookErr = err
			} else {
				for k, v := range u.Environment {
					env[k] = v
				}
				res, err := rt.Runner.Run(ctx, argv, sys.RunOptions{Env: env, ChrootEnv: true, AllowFailure: true, MaxCaptureBytes: 128 * 1024, Timeout: 30 * time.Second})
				if err != nil {
					stopHookErr = err
				} else if res.ReturnCode != 0 {
					stopHookErr = fmt.Errorf("ExecStop exited %d: %s", res.ReturnCode, strings.TrimSpace(res.Stderr))
				}
			}
		}
	}
	if !sys.TerminateProcessIdentity(*id, 2*time.Second) {
		_ = s.writeState(ch, u.Name, "failed", "process tree survived termination")
		return map[string]any{"service": u.Name, "chroot": ch, "status": "failed", "pid": id.PID, "log_file": log}, errors.New("service process tree survived TERM/KILL; identity state retained")
	}
	if e = cleanupServiceIdentity(prefix); e != nil {
		_ = s.writeState(ch, u.Name, "stale", e.Error())
		return map[string]any{"service": u.Name, "chroot": ch, "status": "stale", "pid": id.PID, "log_file": log}, e
	}
	if e = s.writeState(ch, u.Name, "stopped", ""); e != nil {
		return map[string]any{"service": u.Name, "chroot": ch, "status": "stopped", "pid": id.PID, "log_file": log}, e
	}
	_ = appendServiceLifecycle(log, "stopped")
	row := map[string]any{"service": u.Name, "chroot": ch, "status": "stopped", "pid": id.PID, "log_file": log}
	if stopHookErr != nil {
		row["exec_stop_error"] = stopHookErr.Error()
		return row, stopHookErr
	}
	return row, nil
}
func (s *UnitService) Restart(ctx context.Context, name, chroot string) (result map[string]any, err error) {
	defer func() {
		if s.C.DryRun {
			return
		}
		auditErr := s.C.Audit().RecordMutation(context.WithoutCancel(ctx), "service.restart", chroot+":"+name, err, nil)
		err = errors.Join(err, auditErr)
	}()
	st, e := s.Stop(ctx, name, chroot)
	if e != nil {
		return map[string]any{"stopped": st}, e
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
	lines, truncated, readErr := readRecentLogLines(p, tail, 0)
	if os.IsNotExist(readErr) {
		lines = nil
		truncated = false
	} else if readErr != nil {
		return nil, fmt.Errorf("read service journal %s: %w", p, readErr)
	}
	return map[string]any{"service": u.Name, "chroot": ch, "log_file": p, "lines": lines, "text": strings.Join(lines, "\n"), "truncated": truncated}, nil
}

func (s *UnitService) Enable(ctx context.Context, name, chroot, target string) (result map[string]any, err error) {
	defer func() {
		if s.C.DryRun {
			return
		}
		auditErr := s.C.Audit().RecordMutation(context.WithoutCancel(ctx), "service.enable", chroot+":"+name, err, map[string]string{"target": target})
		err = errors.Join(err, auditErr)
	}()
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
func (s *UnitService) Disable(ctx context.Context, name, chroot, target string) (result map[string]any, err error) {
	defer func() {
		if s.C.DryRun {
			return
		}
		auditErr := s.C.Audit().RecordMutation(context.WithoutCancel(ctx), "service.disable", chroot+":"+name, err, map[string]string{"target": target})
		err = errors.Join(err, auditErr)
	}()
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
	if e = os.Remove(p); e != nil && !os.IsNotExist(e) {
		return nil, e
	}
	return map[string]any{"service": u.Name, "chroot": ch, "enabled": false, "target": target}, nil
}
