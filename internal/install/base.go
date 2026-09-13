package install

import (
	"chrootctl/internal/config"
	"chrootctl/internal/controller"
	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Phase string

const (
	Extract   Phase = "extract"
	Bootstrap Phase = "bootstrap"
	Desktop   Phase = "desktop"
	Finalize  Phase = "finalize"
)

var Phases = []Phase{Extract, Bootstrap, Desktop, Finalize}
var ProfileDefaultDesktop = map[string]string{"minimal": "none", "dev": "none", "xfce4": "xfce4", "plasma": "plasma", "custom": "none"}

type Logger interface {
	Infof(string, ...any)
	Warningf(string, ...any)
}
type IdentitySyncer interface {
	SyncID(context.Context, string, bool, bool) (model.UserIdSyncResult, error)
}
type Base struct {
	Config                     config.ChrootConfig
	Runner                     *sys.Runner
	Controller                 *controller.Controller
	Registry                   *registry.Registry
	UserSync                   IdentitySyncer
	Logger                     Logger
	Distro                     string
	MirrorSelection            string
	MirrorBaseURL              string
	MirrorCandidates           []MirrorCandidate
	Resume                     bool
	DeferInstalledFinalization bool
	AllowExistingRootfsReplace bool
	Progress                   func(ProgressEvent) error
	ContextKey                 string
}
type MirrorCandidate struct {
	ID  string `json:"id"`
	URL string `json:"url"`
}
type ReleaseRef struct {
	Label string `json:"label"`
	URL   string `json:"url"`
}
type Request struct {
	Phase                                               *Phase
	Username, Desktop, Version, Release, Profile        string
	ForcePhase, Auto, Resume, Repair, OverwriteExisting bool
	Progress                                            func(ProgressEvent) error
}
type ProgressEvent struct {
	Phase   Phase  `json:"phase"`
	Step    string `json:"step,omitempty"`
	State   string `json:"state"`
	Percent int    `json:"percent"`
	Message string `json:"message"`
}

type DistroInstaller interface {
	BaseInstaller() *Base
	RunPhaseExtract(context.Context, string, string, bool) (model.InstallExtractResult, error)
	RunPhaseBootstrap(context.Context, string, string, bool) (model.InstallBootstrapResult, error)
	RunPhaseDesktop(context.Context, string, string, bool) (model.InstallDesktopResult, error)
	RunPhaseFinalize(context.Context, string, bool) (model.InstallFinalizeResult, error)
	InferPhaseFromFilesystem() Phase
	ReadyForBootstrap() bool
}

func (b *Base) BaseInstaller() *Base { return b }
func PhaseIndex(p Phase) int {
	for i, x := range Phases {
		if x == p {
			return i
		}
	}
	return -1
}
func NextPhase(p Phase) (Phase, bool) {
	i := PhaseIndex(p)
	if i >= 0 && i+1 < len(Phases) {
		return Phases[i+1], true
	}
	return "", false
}
func (b *Base) ConfigureMirrorPlan(selection, baseURL string, candidates []MirrorCandidate) {
	if selection == "" {
		selection = "auto"
	}
	b.MirrorSelection = selection
	b.MirrorBaseURL = strings.TrimRight(baseURL, "/")
	b.MirrorCandidates = nil
	for _, c := range candidates {
		c.ID = strings.TrimSpace(c.ID)
		c.URL = strings.TrimRight(strings.TrimSpace(c.URL), "/")
		if c.ID != "" && c.URL != "" {
			b.MirrorCandidates = append(b.MirrorCandidates, c)
		}
	}
}
func (b *Base) SelectedProfile(profile string) string {
	if profile != "" {
		return profile
	}
	if b.Config.InstallProfile != nil && *b.Config.InstallProfile != "" {
		return *b.Config.InstallProfile
	}
	return "minimal"
}
func (b *Base) SelectedDesktop(desktop, profile string) (string, error) {
	p := b.SelectedProfile(profile)
	d := strings.TrimSpace(desktop)
	if d == "" {
		d = "auto"
	}
	if p == "minimal" {
		if d != "auto" && d != "none" {
			return "", errors.New("minimal profile does not allow desktop installation; choose profile xfce4/plasma or desktop none")
		}
		return "none", nil
	}
	if d == "auto" {
		if x, ok := ProfileDefaultDesktop[p]; ok {
			return x, nil
		}
		return "none", nil
	}
	return d, nil
}
func (b *Base) CurrentPhase(ctx context.Context) Phase {
	if b.Runner != nil && b.Runner.DryRun {
		return Extract
	}
	if b.Registry == nil {
		return Extract
	}
	r, e := b.Registry.Get(ctx, b.Config.DistroName)
	if e != nil || r == nil {
		return Extract
	}
	p := Phase(r.Phase)
	if PhaseIndex(p) < 0 {
		return Extract
	}
	return p
}
func (b *Base) AssertPhaseAllowed(ctx context.Context, requested Phase, force bool) error {
	if force {
		return nil
	}
	current := b.CurrentPhase(ctx)
	if PhaseIndex(requested) < PhaseIndex(current) {
		return fmt.Errorf("cannot run phase %s after %s without force", requested, current)
	}
	return nil
}
func strptr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
func (b *Base) MarkPhase(ctx context.Context, phase Phase, installed bool, version, release string, metadata map[string]any) error {
	if b.Runner != nil && b.Runner.DryRun {
		return nil
	}
	if b.Registry == nil {
		return errors.New("registry is nil")
	}
	rec, _ := b.Registry.Get(ctx, b.Config.DistroName)
	merged := map[string]any{}
	var arch, rel, ver *string
	if rec != nil {
		for k, v := range rec.Metadata {
			merged[k] = v
		}
		arch = rec.Arch
		rel = rec.ReleaseName
		ver = rec.Version
	}
	for k, v := range metadata {
		merged[k] = v
	}
	if arch == nil {
		arch = strptr(b.Config.TargetArch)
	}
	if release != "" {
		rel = strptr(release)
	}
	if version != "" {
		ver = strptr(version)
	}
	return b.Registry.Upsert(ctx, registry.ChrootInput{Name: b.Config.DistroName, Distro: b.Distro, Path: b.Config.ChrootBase(), Arch: arch, ReleaseName: rel, Version: ver, Phase: string(phase), Installed: installed, Metadata: merged})
}
func (b *Base) ChrootShell(ctx context.Context, command string, allowFailure bool) (sys.RunResult, error) {
	return b.Runner.Run(ctx, []string{"busybox", "chroot", b.Config.ChrootBase(), "/bin/bash", "-lc", command}, sys.RunOptions{ChrootEnv: true, AllowFailure: allowFailure})
}
func (b *Base) RequireChrootCommands(ctx context.Context, commands ...string) error {
	missing := []string{}
	for _, c := range commands {
		r, _ := b.ChrootShell(ctx, "command -v "+shellQuote(c)+" >/dev/null 2>&1", true)
		if r.ReturnCode != 0 {
			missing = append(missing, c)
		}
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing chroot command: %s; run install --phase bootstrap --repair", strings.Join(missing, ", "))
	}
	return nil
}
func shellQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'" }
func (b *Base) EnsureExecutionSupported() error {
	host := sys.HostArch()
	if host == "" || host == b.Config.TargetArch {
		return nil
	}
	if sys.CanExecuteForeignArch(b.Config.TargetArch) {
		if b.Logger != nil {
			b.Logger.Infof("detected foreign-arch execution support for %s via qemu/binfmt", b.Config.TargetArch)
		}
		return nil
	}
	q := sys.QEMUUserBinaryNames(b.Config.TargetArch)[0]
	return fmt.Errorf("target arch %s differs from host arch %s; extract is supported, but bootstrap/desktop/finalize/upgrade require user-mode emulation such as %s. Install %s and enable binfmt_misc, or create the rootfs with 'chrootctl install ... --phase extract --arch %s', then export/import it to your %s phone.", b.Config.TargetArch, host, q, q, b.Config.TargetArch, b.Config.TargetArch)
}
func (b *Base) EnsureCommonBootstrapPrereqs(ctx context.Context) error {
	if b.Controller == nil {
		return errors.New("controller is nil")
	}
	m := b.Controller.Mount(ctx)
	if m.Failed > 0 {
		return fmt.Errorf("mount failed: %s", strings.Join(m.Errors, "; "))
	}
	f := b.Controller.FixTTY(ctx)
	if f.Failed > 0 {
		return fmt.Errorf("tty preparation failed: %s", strings.Join(f.Errors, "; "))
	}
	lines := []string{}
	for _, s := range b.Config.DNSServers {
		lines = append(lines, "nameserver "+s)
	}
	_, e := b.ChrootShell(ctx, "printf %s "+shellQuote(strings.Join(lines, "\\n")+"\\n")+" > /etc/resolv.conf", false)
	if e != nil {
		return e
	}
	_, e = b.ChrootShell(ctx, `printf "127.0.0.1 localhost\n::1 localhost\n" > /etc/hosts`, false)
	return e
}
func (b *Base) NewWorkDir(label string) (string, error) {
	parent := filepath.Dir(b.Config.ChrootBase())
	return os.MkdirTemp(parent, "."+b.Config.DistroName+"."+label+"-")
}
func (b *Base) AssertInstallTargetUnmounted() error {
	table, e := sys.MountTable("/proc/mounts")
	if e != nil {
		return e
	}
	target, _ := filepath.Abs(b.Config.ChrootBase())
	for pair := range table {
		dst, _ := filepath.Abs(pair[1])
		if dst == target || strings.HasPrefix(dst, target+string(os.PathSeparator)) {
			return fmt.Errorf("refusing rootfs replacement while target is mounted: %s", pair[1])
		}
	}
	return nil
}
func (b *Base) PromoteStagedRootFS(ctx context.Context, staged string) error {
	if b.Runner != nil && b.Runner.DryRun {
		return nil
	}
	target := b.Config.ChrootBase()
	if filepath.Dir(staged) != filepath.Dir(target) {
		return errors.New("install staging must share the target filesystem")
	}
	if e := b.AssertInstallTargetUnmounted(); e != nil {
		return e
	}
	parent := filepath.Dir(target)
	backup := filepath.Join(parent, "."+filepath.Base(target)+".preinstall-"+fmt.Sprint(time.Now().UnixNano()))
	had := false
	if _, e := os.Stat(target); e == nil {
		had = true
		if !b.AllowExistingRootfsReplace {
			return fmt.Errorf("target rootfs already exists at %s; pass --overwrite-existing only after taking a snapshot or choosing resume/repair", target)
		}
	}
	id := ""
	var e error
	if b.Registry != nil {
		id, e = b.Registry.BeginFSMutation(ctx, "install.extract", b.Config.DistroName, staged, target, map[string]any{"stage": staged, "backup": backup, "had_existing": had})
		if e != nil {
			return e
		}
		if e = b.Registry.UpdateFSMutation(ctx, id, registry.FSMutationStaged, map[string]any{"stage": staged, "backup": backup, "had_existing": had}); e != nil {
			return e
		}
	}
	transition := func(state string, detail map[string]any) error {
		if b.Registry == nil || id == "" {
			return nil
		}
		return b.Registry.UpdateFSMutation(context.WithoutCancel(ctx), id, state, detail)
	}
	rollback := func(cause error, promoted, moved bool) error {
		var rb error
		if promoted {
			if x := os.Rename(target, staged); x != nil {
				rb = errors.Join(rb, x)
			}
		}
		if moved {
			if x := os.Rename(backup, target); x != nil {
				rb = errors.Join(rb, x)
			}
		}
		if x := mutation.SyncDir(parent); x != nil {
			rb = errors.Join(rb, x)
		}
		if rb == nil {
			if x := transition(registry.FSMutationRolledBack, map[string]any{"error": cause.Error()}); x != nil {
				return errors.Join(cause, x)
			}
			return cause
		}
		if persistErr := transition(registry.FSMutationRepairRequired, map[string]any{"error": cause.Error(), "rollback_error": rb.Error()}); persistErr != nil {
			return errors.Join(cause, rb, persistErr)
		}
		return errors.Join(cause, rb)
	}
	moved := false
	if had {
		if e = os.Rename(target, backup); e != nil {
			return rollback(e, false, false)
		}
		moved = true
		if e = mutation.SyncDir(parent); e != nil {
			return rollback(e, false, true)
		}
	}
	if e = transition(registry.FSMutationPromoting, map[string]any{"stage": staged, "backup": backup, "had_existing": had}); e != nil {
		return rollback(e, false, moved)
	}
	if e = os.Rename(staged, target); e != nil {
		return rollback(e, false, moved)
	}
	promoted := true
	if e = mutation.SyncDir(parent); e != nil {
		return rollback(e, true, moved)
	}
	if e = b.MarkPhase(ctx, Extract, false, "", "", map[string]any{"_chrootctl_install_mutation_id": id}); e != nil {
		return rollback(e, promoted, moved)
	}
	if e = transition(registry.FSMutationCommitted, map[string]any{"backup": backup, "had_existing": had}); e != nil {
		return fmt.Errorf("install promotion committed but mutation journal commit failed: %w", e)
	}
	if moved {
		if e = os.RemoveAll(backup); e != nil {
			if u := transition(registry.FSMutationCleanupDebt, map[string]any{"cleanup_error": e.Error(), "backup": backup}); u != nil {
				return errors.Join(e, u)
			}
			return nil
		}
	}
	if e = transition(registry.FSMutationComplete, nil); e != nil {
		return fmt.Errorf("install promotion committed but terminal journal persistence failed: %w", e)
	}
	return nil
}
func (b *Base) CreateSnapshot(ctx context.Context, reason string) (string, error) {
	if !b.Config.SnapshotBeforeDestructive {
		return "", nil
	}
	if _, e := os.Stat(b.Config.ChrootBase()); e != nil {
		return "", nil
	}
	path := filepath.Join(b.Config.SnapshotDir, b.Config.DistroName+"-"+reason+".tar.gz")
	if b.Runner == nil || !b.Runner.DryRun {
		if e := os.MkdirAll(b.Config.SnapshotDir, 0o755); e != nil {
			return "", e
		}
	}
	_, e := b.Runner.Run(ctx, []string{"tar", "czf", path, b.Config.DistroName}, sys.RunOptions{Cwd: b.Config.ChrootRoot})
	return path, e
}
func cloneMap(m map[string]any) map[string]any {
	r := map[string]any{}
	for k, v := range m {
		r[k] = v
	}
	return r
}
func (b *Base) transaction(ctx context.Context) map[string]any {
	if b.Registry == nil {
		return map[string]any{"version": 2, "steps": map[string]any{}}
	}
	r, _ := b.Registry.Get(ctx, b.Config.DistroName)
	if r != nil {
		if raw, ok := r.Metadata["install_transaction"].(map[string]any); ok {
			if steps, ok := raw["steps"].(map[string]any); ok {
				return map[string]any{"version": 2, "steps": cloneMap(steps)}
			}
		}
	}
	return map[string]any{"version": 2, "steps": map[string]any{}}
}
func (b *Base) RecordStep(ctx context.Context, step, state, errText string) error {
	if b.Runner != nil && b.Runner.DryRun {
		return nil
	}
	if b.Registry == nil {
		return errors.New("registry is nil")
	}
	r, e := b.Registry.Get(ctx, b.Config.DistroName)
	if e != nil {
		return e
	}
	if r == nil {
		input := registry.ChrootInput{Name: b.Config.DistroName, Distro: b.Distro, Path: b.Config.ChrootBase(), Arch: strptr(b.Config.TargetArch), Phase: string(Extract), Installed: false, Metadata: map[string]any{}}
		if e := b.Registry.Upsert(ctx, input); e != nil {
			return e
		}
		r, e = b.Registry.Get(ctx, b.Config.DistroName)
		if e != nil {
			return e
		}
		if r == nil {
			return errors.New("chroot registry record missing after install transaction seed")
		}
	}
	meta := cloneMap(r.Metadata)
	tx := b.transaction(ctx)
	steps, _ := tx["steps"].(map[string]any)
	row := map[string]any{"state": state, "updated_at": float64(time.Now().UnixNano()) / 1e9}
	if b.ContextKey != "" {
		row["context"] = b.ContextKey
	}
	if errText != "" {
		if len(errText) > 1000 {
			errText = errText[:1000]
		}
		row["error"] = errText
	}
	steps[step] = row
	meta["install_transaction"] = map[string]any{"version": 2, "steps": steps}
	return b.Registry.Upsert(ctx, registry.ChrootInput{Name: r.Name, Distro: r.Distro, Path: r.Path, Arch: r.Arch, ReleaseName: r.ReleaseName, Version: r.Version, Phase: r.Phase, Installed: r.Installed, Metadata: meta})
}
func (b *Base) emitProgress(ctx context.Context, event ProgressEvent) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if b.Progress == nil {
		return nil
	}
	return b.Progress(event)
}

func (b *Base) RunSubstep(ctx context.Context, phase Phase, name string, resumable bool, fn func() error) error {
	step := string(phase) + "." + name
	tx := b.transaction(ctx)
	steps, _ := tx["steps"].(map[string]any)
	if b.Resume && resumable {
		if row, ok := steps[step].(map[string]any); ok && row["state"] == "completed" {
			old, _ := row["context"].(string)
			if old == "" || old != b.ContextKey {
				return fmt.Errorf("cannot resume %s: install request context changed; start a new explicit install/repair plan", step)
			}
			return nil
		}
	}
	if e := b.RecordStep(ctx, step, "running", ""); e != nil {
		return e
	}
	if e := b.emitProgress(ctx, ProgressEvent{Phase: phase, Step: name, State: "running", Percent: phaseStartPercent(phase), Message: "Running " + step}); e != nil {
		return e
	}
	if e := fn(); e != nil {
		if persistErr := b.RecordStep(context.WithoutCancel(ctx), step, "failed", e.Error()); persistErr != nil {
			return errors.Join(e, persistErr)
		}
		return e
	}
	if e := b.RecordStep(ctx, step, "completed", ""); e != nil {
		return e
	}
	return b.emitProgress(ctx, ProgressEvent{Phase: phase, Step: name, State: "completed", Percent: phaseEndPercent(phase), Message: "Completed " + step})
}
func (b *Base) ResumeStartPhase(ctx context.Context, repair bool) Phase {
	tx := b.transaction(ctx)
	steps, _ := tx["steps"].(map[string]any)
	if len(steps) > 0 {
		if repair {
			for _, p := range Phases {
				if row, ok := steps[string(p)].(map[string]any); ok && (row["state"] == "failed" || row["state"] == "running") {
					return p
				}
			}
		}
		for _, p := range Phases {
			row, ok := steps[string(p)].(map[string]any)
			if !ok || row["state"] != "completed" {
				return p
			}
		}
		return Finalize
	}
	return b.CurrentPhase(ctx)
}
func Run(ctx context.Context, d DistroInstaller, req Request) ([]model.InstallerResult, error) {
	b := d.BaseInstaller()
	b.Resume = req.Resume || req.Repair
	b.AllowExistingRootfsReplace = req.OverwriteExisting || req.Repair
	b.Progress = req.Progress
	if req.Username == "" {
		req.Username = b.Config.Username
	}
	if !req.Repair && (req.Auto || req.Resume || req.Phase == nil) && b.Registry != nil {
		r, _ := b.Registry.Get(ctx, b.Config.DistroName)
		if r != nil && r.Installed {
			return []model.InstallerResult{model.InstallAlreadyCompleteResult{Installed: true, Status: "already-installed", Phase: "finalize"}}, nil
		}
	}
	profile := b.SelectedProfile(req.Profile)
	desktop, e := b.SelectedDesktop(req.Desktop, profile)
	if e != nil {
		return nil, e
	}
	b.ContextKey = strings.Join([]string{b.Distro, b.Config.TargetArch, b.Config.DistroName, req.Username, profile, desktop, req.Version, req.Release}, "|")
	runOne := func(p Phase) (model.InstallerResult, error) {
		if e := b.emitProgress(ctx, ProgressEvent{Phase: p, State: "running", Percent: phaseStartPercent(p), Message: "Starting install phase " + string(p)}); e != nil {
			return nil, e
		}
		if e := b.RecordStep(ctx, string(p), "running", ""); e != nil {
			return nil, e
		}
		var r model.InstallerResult
		var e error
		switch p {
		case Extract:
			var x model.InstallExtractResult
			x, e = d.RunPhaseExtract(ctx, req.Version, req.Release, req.ForcePhase || req.Repair)
			r = x
		case Bootstrap:
			var x model.InstallBootstrapResult
			x, e = d.RunPhaseBootstrap(ctx, req.Username, profile, req.ForcePhase || req.Repair)
			r = x
		case Desktop:
			var x model.InstallDesktopResult
			x, e = d.RunPhaseDesktop(ctx, desktop, profile, req.ForcePhase || req.Repair)
			r = x
		case Finalize:
			var x model.InstallFinalizeResult
			x, e = d.RunPhaseFinalize(ctx, req.Username, req.ForcePhase || req.Repair)
			r = x
		}
		if e != nil {
			if persistErr := b.RecordStep(context.WithoutCancel(ctx), string(p), "failed", e.Error()); persistErr != nil {
				return nil, errors.Join(e, persistErr)
			}
			return nil, e
		}
		if e = b.RecordStep(ctx, string(p), "completed", ""); e != nil {
			return nil, e
		}
		if e = b.emitProgress(ctx, ProgressEvent{Phase: p, State: "completed", Percent: phaseEndPercent(p), Message: "Completed install phase " + string(p)}); e != nil {
			return nil, e
		}
		return r, nil
	}
	if req.Auto || req.Resume || req.Repair || req.Phase == nil {
		start := b.ResumeStartPhase(ctx, req.Repair)
		if req.Phase != nil && !req.Resume && !req.Repair {
			start = *req.Phase
		}
		out := []model.InstallerResult{}
		for _, p := range Phases[PhaseIndex(start):] {
			if req.Resume && !req.Repair {
				tx := b.transaction(ctx)
				if row, ok := tx["steps"].(map[string]any)[string(p)].(map[string]any); ok && row["state"] == "completed" {
					continue
				}
			}
			r, e := runOne(p)
			if e != nil {
				return out, e
			}
			out = append(out, r)
		}
		return out, nil
	}
	p := Extract
	if req.Phase != nil {
		p = *req.Phase
	}
	r, e := runOne(p)
	if e != nil {
		return nil, e
	}
	return []model.InstallerResult{r}, nil
}
func (b *Base) Finalize(ctx context.Context, username string, force bool) (model.InstallFinalizeResult, error) {
	if e := b.EnsureExecutionSupported(); e != nil {
		return model.InstallFinalizeResult{}, e
	}
	if e := b.AssertPhaseAllowed(ctx, Finalize, force); e != nil {
		return model.InstallFinalizeResult{}, e
	}
	snap, e := b.CreateSnapshot(ctx, "finalize")
	if e != nil {
		return model.InstallFinalizeResult{}, e
	}
	if locale := strings.TrimSpace(b.Config.Locale); locale != "" {
		e = b.RunSubstep(ctx, Finalize, "locale", true, func() error { return b.ApplyConfiguredLocale(ctx, locale) })
		if e != nil {
			return model.InstallFinalizeResult{}, e
		}
	}
	if b.UserSync != nil {
		e = b.RunSubstep(ctx, Finalize, "uid-sync", true, func() error { _, x := b.UserSync.SyncID(ctx, username, true, true); return x })
		if e != nil {
			return model.InstallFinalizeResult{}, e
		}
	}
	for index, hook := range b.Config.PostInstallHooks {
		hook = strings.TrimSpace(hook)
		if hook == "" {
			continue
		}
		step := fmt.Sprintf("post-hook-%02d", index+1)
		e = b.RunSubstep(ctx, Finalize, step, false, func() error { return b.RunPostInstallHook(ctx, hook) })
		if e != nil {
			return model.InstallFinalizeResult{}, e
		}
	}
	installed := !b.DeferInstalledFinalization
	status := strptr("finalized")
	if !installed {
		status = strptr("pending-catalog")
	}
	if e = b.MarkPhase(ctx, Finalize, installed, "", "", map[string]any{"uid_sync": b.UserSync != nil, "finalize_snapshot": snap, "locale": strings.TrimSpace(b.Config.Locale), "post_install_hooks": len(b.Config.PostInstallHooks), "install_status": *status}); e != nil {
		return model.InstallFinalizeResult{}, e
	}
	return model.InstallFinalizeResult{Installed: installed, UidSync: b.UserSync != nil, Snapshot: snap, Status: status, Phase: "finalize"}, nil
}

func phaseStartPercent(phase Phase) int {
	switch phase {
	case Extract:
		return 10
	case Bootstrap:
		return 35
	case Desktop:
		return 60
	case Finalize:
		return 82
	default:
		return 5
	}
}

func phaseEndPercent(phase Phase) int {
	switch phase {
	case Extract:
		return 30
	case Bootstrap:
		return 55
	case Desktop:
		return 78
	case Finalize:
		return 92
	default:
		return 10
	}
}

func (b *Base) ApplyConfiguredLocale(ctx context.Context, locale string) error {
	locale = strings.TrimSpace(locale)
	if locale == "" {
		return nil
	}
	quoted := ShellQuote(locale)
	cmd := "if command -v locale-gen >/dev/null 2>&1; then " +
		"grep -q '^" + locale + " ' /etc/locale.gen 2>/dev/null || printf '%s UTF-8\\n' " + quoted + " >> /etc/locale.gen; " +
		"locale-gen " + quoted + "; fi; " +
		"printf 'LANG=%s\\nLC_ALL=%s\\n' " + quoted + " " + quoted + " > /etc/default/locale"
	_, err := b.ChrootShell(ctx, cmd, false)
	return err
}

func (b *Base) RunPostInstallHook(ctx context.Context, hook string) error {
	if strings.TrimSpace(hook) == "" {
		return nil
	}
	_, err := b.ChrootShell(ctx, hook, false)
	return err
}
