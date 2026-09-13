package services

import (
	"chrootctl/internal/install"
	ifactory "chrootctl/internal/install/factory"
	"chrootctl/internal/model"
	sys "chrootctl/internal/system"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type InstallService struct{ C *Container }

func (s *InstallService) Distros() []string  { return install.OptionIDs(install.DistroOptions()) }
func (s *InstallService) Profiles() []string { return install.OptionIDs(install.ProfileOptions()) }
func (s *InstallService) Desktops() []string { return install.OptionIDs(install.DesktopOptions()) }
func (s *InstallService) Architectures(distro string) []string {
	return install.OptionIDs(install.ArchitectureOptions(distro))
}
func (s *InstallService) Presets() []string { return install.OptionIDs(install.PresetOptions()) }
func (s *InstallService) Mirrors(distro string) []string {
	return install.OptionIDs(install.MirrorOptions(distro))
}

func (s *InstallService) build(ctx context.Context, distro, name, username, arch string) (install.DistroInstaller, Runtime, error) {
	rt, e := s.C.RuntimeFor(name, username)
	if e != nil {
		return nil, Runtime{}, e
	}
	if arch != "" {
		rt.Config.TargetArch = arch
		rt.Controller.Config = rt.Config
		rt.Users.Config = rt.Config
	}
	base := &install.Base{Config: rt.Config, Runner: rt.Runner, Controller: rt.Controller, Registry: s.C.Registry, UserSync: rt.Users, Logger: s.C.Logger, Distro: distro}
	d, e := ifactory.Build(distro, base)
	return d, rt, e
}
func (s *InstallService) ListVersions(ctx context.Context, distro, name, username string) ([]install.ReleaseRef, error) {
	if name == "" {
		name = distro
	}
	d, _, e := s.build(ctx, distro, name, username, "")
	if e != nil {
		return nil, e
	}
	type lister interface {
		ListVersions() ([]install.ReleaseRef, error)
	}
	if x, ok := d.(lister); ok {
		return x.ListVersions()
	}
	return []install.ReleaseRef{}, nil
}
func (s *InstallService) normalize(req model.InstallRequest) (install.NormalizedRequest, []install.ValidationIssue) {
	return install.NormalizeInstallShape(
		req.Distro,
		req.Name,
		req.Username,
		req.Arch,
		ptrText(req.Preset),
		ptrText(req.Profile),
		ptrText(req.Desktop),
		ptrText(req.Release),
		ptrText(req.Version),
		ptrText(req.Mirror),
		ptrText(req.Phase),
		req.ForcePhase,
		req.Resume,
		req.Repair,
		req.OverwriteExisting,
		req.Tools,
		req.Addons,
		s.C.BaseConfig.Username,
		s.C.BaseConfig.TargetArch,
	)
}
func (s *InstallService) normalizedRequest(req model.InstallRequest) (model.InstallRequest, install.NormalizedRequest, []install.ValidationIssue) {
	n, issues := s.normalize(req)
	preset, profile, desktop, release, version, mirror, phase := n.Preset, n.Profile, n.Desktop, n.Release, n.Version, n.Mirror, n.Phase
	out := req
	out.Distro = n.Distro
	out.Name = n.Name
	out.Username = n.Username
	out.Arch = n.Arch
	out.Preset = &preset
	out.Profile = &profile
	out.Desktop = &desktop
	out.Release = installStringPtr(release)
	out.Version = installStringPtr(version)
	out.Mirror = &mirror
	out.Phase = installStringPtr(phase)
	out.ForcePhase = n.ForcePhase
	out.Resume = n.Resume
	out.Repair = n.Repair
	out.OverwriteExisting = n.OverwriteExisting
	out.Tools = n.Tools
	out.Addons = n.Addons
	return out, n, issues
}
func (s *InstallService) ValidateRequest(req model.InstallRequest) map[string]any {
	_, n, shapeIssues := s.normalizedRequest(req)
	blocking := []map[string]string{}
	for _, issue := range shapeIssues {
		blocking = append(blocking, map[string]string{"code": issue.Code, "message": issue.Message})
	}
	if n.Name == "" {
		blocking = append(blocking, map[string]string{"code": "missing_name", "message": "Install requires a chroot name."})
	}
	if n.Username == "" {
		blocking = append(blocking, map[string]string{"code": "missing_username", "message": "Install requires a target username."})
	}
	mode := "native"
	if n.Arch != sys.HostArch() {
		mode = "extract-only"
		if sys.CanExecuteForeignArch(n.Arch) {
			mode = "foreign-ready"
		} else if n.Phase != string(install.Extract) {
			blocking = append(blocking, map[string]string{"code": "foreign_arch_not_ready", "message": "Target architecture " + n.Arch + " requires qemu/binfmt execution support for bootstrap, desktop, finalize, and upgrade. Use --phase extract or install user-mode emulation first."})
		}
	}
	return map[string]any{
		"ok":             len(blocking) == 0,
		"blocking":       blocking,
		"warnings":       installWarnings(n),
		"distro":         n.Distro,
		"name":           n.Name,
		"username":       n.Username,
		"arch":           n.Arch,
		"preset":         n.Preset,
		"profile":        n.Profile,
		"desktop":        n.Desktop,
		"mirror":         n.Mirror,
		"execution_mode": mode,
		"phases":         install.InstallPhasesFrom(n.Phase),
		"requirements": map[string]any{
			"username_required":             true,
			"default_username":              s.C.BaseConfig.Username,
			"supported_distros":             s.Distros(),
			"supported_profiles":            s.Profiles(),
			"supported_desktops":            s.Desktops(),
			"supported_architectures":       s.Architectures(n.Distro),
			"overwrite_existing_required":   false,
			"safety_snapshot_before_modify": s.C.BaseConfig.SnapshotBeforeDestructive,
		},
	}
}
func installWarnings(n install.NormalizedRequest) []string {
	warnings := []string{}
	if len(n.Tools) > 0 || len(n.Addons) > 0 {
		warnings = append(warnings, "The chroot is marked installed only after selected tools/add-ons finish successfully.")
	}
	if n.Repair {
		warnings = append(warnings, "Repair mode starts from failed/observed installer state and may rerun incomplete steps.")
	}
	if n.OverwriteExisting {
		warnings = append(warnings, "Existing rootfs replacement was explicitly requested.")
	}
	return warnings
}
func (s *InstallService) WizardDefaults(ctx context.Context) (model.InstallWizardDefaults, error) {
	rows, e := s.C.Registry.List(ctx)
	if e != nil {
		return model.InstallWizardDefaults{}, e
	}
	d := model.InstallWizardDefaults{Tools: []string{}, Addons: []string{}}
	if len(rows) > 0 {
		r := rows[0]
		d.Name = &r.Name
		d.Distro = &r.Distro
		if p := fmt.Sprint(r.Metadata["profile"]); p != "<nil>" && p != "" {
			d.Profile = &p
		}
		if x := fmt.Sprint(r.Metadata["desktop"]); x != "<nil>" && x != "" {
			d.Desktop = &x
		}
		if r.ReleaseName != nil {
			d.Release = r.ReleaseName
		}
		if r.Version != nil {
			d.Version = r.Version
		}
	} else {
		a := "ubuntu"
		d.Distro = &a
		d.Name = &a
	}
	if s.C.BaseConfig.Username != "" {
		u := s.C.BaseConfig.Username
		d.Username = &u
	}
	if d.Profile == nil {
		p := "minimal"
		d.Profile = &p
	}
	if d.Desktop == nil {
		x := "none"
		d.Desktop = &x
	}
	p := "minimal-server"
	d.Preset = &p
	return d, nil
}
func (s *InstallService) InstallFormState(ctx context.Context, name, distro string) (map[string]any, error) {
	d, e := s.WizardDefaults(ctx)
	if e != nil {
		return nil, e
	}
	if name != "" {
		d.Name = &name
	}
	if distro != "" {
		d.Distro = &distro
	}
	chosenDistro := ptrText(d.Distro)
	return map[string]any{
		"defaults":      d,
		"distros":       install.DistroOptions(),
		"architectures": install.ArchitectureOptions(chosenDistro),
		"presets":       install.PresetOptions(),
		"profiles":      install.ProfileOptions(),
		"desktops":      install.DesktopOptions(),
		"mirrors":       install.MirrorOptions(chosenDistro),
		"users":         []map[string]string{},
		"cross_arch":    s.C.System().CrossArchState(),
	}, nil
}
func (s *InstallService) PreviewInstall(req model.InstallRequest) map[string]any {
	_, n, _ := s.normalizedRequest(req)
	plan := s.ValidateRequest(req)
	plan["kind"] = "install"
	plan["confirm"] = true
	plan["tools"] = n.Tools
	plan["addons"] = n.Addons
	plan["request"] = map[string]any{"distro": n.Distro, "name": n.Name, "username": n.Username, "arch": n.Arch, "preset": n.Preset, "profile": n.Profile, "desktop": n.Desktop, "release": installEmptyNil(n.Release), "version": installEmptyNil(n.Version), "mirror": n.Mirror, "phase": installEmptyNil(n.Phase), "resume": n.Resume, "repair": n.Repair, "overwrite_existing": n.OverwriteExisting}
	plan["message"] = map[bool]string{true: "Install preview is ready.", false: "Install preview has blocking issues."}[plan["ok"].(bool)]
	plan["resume"] = map[string]any{"available": n.Resume || n.Repair, "repair": n.Repair}
	plan["progress_milestones"] = []map[string]any{{"phase": "extract", "percent": 10}, {"phase": "bootstrap", "percent": 35}, {"phase": "desktop", "percent": 60}, {"phase": "finalize", "percent": 82}, {"phase": "catalog", "percent": 94}, {"phase": "complete", "percent": 100}}
	return plan
}
func phasePtr(sv *string) *install.Phase {
	if sv == nil || *sv == "" {
		return nil
	}
	p := install.Phase(*sv)
	return &p
}
func (s *InstallService) Install(ctx context.Context, req model.InstallRequest, progress func(any) error) (model.InstallRunResult, error) {
	normalized, n, _ := s.normalizedRequest(req)
	plan := s.ValidateRequest(normalized)
	if ok, _ := plan["ok"].(bool); !ok {
		return model.InstallRunResult{}, fmt.Errorf("invalid install request: %v", plan["blocking"])
	}
	if err := s.checkExistingTarget(ctx, n); err != nil {
		return model.InstallRunResult{}, err
	}
	d, _, e := s.build(ctx, n.Distro, n.Name, n.Username, n.Arch)
	if e != nil {
		return model.InstallRunResult{}, e
	}
	deferCatalogMark := len(n.Tools) > 0 || len(n.Addons) > 0
	d.BaseInstaller().DeferInstalledFinalization = deferCatalogMark
	if progress != nil {
		_ = progress(map[string]any{"phase": "validate", "message": "Install request validated", "percent": 8, "plan": plan})
	}
	phaseResults, e := install.Run(ctx, d, install.Request{Phase: phasePtr(normalized.Phase), Username: n.Username, Desktop: n.Desktop, Version: n.Version, Release: n.Release, Profile: n.Profile, ForcePhase: n.ForcePhase, Auto: normalized.Phase == nil, Resume: n.Resume, Repair: n.Repair, OverwriteExisting: n.OverwriteExisting, Progress: func(ev install.ProgressEvent) error {
		if progress == nil {
			return nil
		}
		return progress(map[string]any{"phase": string(ev.Phase), "step": ev.Step, "state": ev.State, "message": ev.Message, "percent": ev.Percent})
	}})
	if e != nil {
		return model.InstallRunResult{}, e
	}
	if progress != nil {
		_ = progress(map[string]any{"phase": "catalog", "message": "Applying selected tools and addons", "percent": 94})
	}
	result := model.InstallRunResult{ChrootName: n.Name, Distro: n.Distro, Phases: phaseResults, ToolResults: []model.CatalogApplyResult{}, AddonResults: []model.CatalogApplyResult{}}
	tools, e := s.C.Catalog("tool", n.Name).Apply(ctx, n.Tools, progress)
	result.ToolResults = tools
	if e != nil {
		return result, e
	}
	addons, e := s.C.Catalog("addon", n.Name).Apply(ctx, n.Addons, progress)
	result.AddonResults = addons
	if e != nil {
		return result, e
	}
	if deferCatalogMark {
		if e = d.BaseInstaller().MarkPhase(ctx, install.Finalize, true, "", "", map[string]any{"catalog_tools": n.Tools, "catalog_addons": n.Addons, "install_status": "complete"}); e != nil {
			return result, e
		}
	}
	if progress != nil {
		_ = progress(map[string]any{"phase": "complete", "message": "Install completed", "percent": 100})
	}
	result.NextSteps = []string{"chrootctl --name " + n.Name + " start --login", "chrootctl --name " + n.Name + " logs --all"}
	return result, nil
}
func (s *InstallService) checkExistingTarget(ctx context.Context, n install.NormalizedRequest) error {
	if n.Repair || n.Resume || n.OverwriteExisting || (n.Phase != "" && n.Phase != string(install.Extract)) {
		return nil
	}
	target := filepath.Join(s.C.BaseConfig.ChrootRoot, n.Name)
	if _, err := os.Stat(target); err != nil {
		return nil
	}
	rec, err := s.C.Registry.Get(ctx, n.Name)
	if err != nil {
		return err
	}
	if rec == nil {
		return fmt.Errorf("target rootfs already exists at %s without a registry owner; pass --overwrite-existing only after reviewing the directory or choose a different --name", target)
	}
	return nil
}
func (s *InstallService) Upgrade(ctx context.Context, name, username string, progress func(any) error) (model.UpgradeResult, error) {
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil || r == nil {
		if e == nil {
			e = fmt.Errorf("no registry record for chroot: %s", name)
		}
		return model.UpgradeResult{}, e
	}
	if !r.Installed || r.Phase != string(install.Finalize) {
		return model.UpgradeResult{}, fmt.Errorf("upgrade requires an installed finalized chroot; current phase=%s installed=%v", r.Phase, r.Installed)
	}
	if r.Distro != "ubuntu" && r.Distro != "arch" {
		return model.UpgradeResult{}, fmt.Errorf("upgrade does not support registered distro %q", r.Distro)
	}
	if username == "" {
		username = s.C.BaseConfig.Username
	}
	if username == "" {
		return model.UpgradeResult{}, fmt.Errorf("upgrade requires a username")
	}
	rt, e := s.C.RuntimeFor(name, username)
	if e != nil {
		return model.UpgradeResult{}, e
	}
	if filepath.Clean(rt.Config.ChrootBase()) != filepath.Clean(r.Path) {
		return model.UpgradeResult{}, fmt.Errorf("upgrade target mismatch: runtime path %s differs from registry path %s", rt.Config.ChrootBase(), r.Path)
	}
	base := &install.Base{Config: rt.Config, Runner: rt.Runner, Controller: rt.Controller, Registry: s.C.Registry, UserSync: rt.Users, Logger: s.C.Logger, Distro: r.Distro}
	if err := rt.Runner.RequireRoot(); err != nil {
		return model.UpgradeResult{}, err
	}
	if err := base.EnsureExecutionSupported(); err != nil {
		return model.UpgradeResult{}, err
	}
	if err := base.EnsureCommonBootstrapPrereqs(ctx); err != nil {
		return model.UpgradeResult{}, err
	}
	if progress != nil {
		_ = progress(map[string]any{"phase": "upgrade", "percent": 25, "message": "Upgrading chroot"})
	}
	snap := ""
	if s.C.BaseConfig.SnapshotBeforeDestructive {
		snapshotName := uniqueSnapshotName("pre-upgrade")
		x, snapshotErr := s.C.Snapshots().Create(ctx, name, snapshotName, "Automatic pre-upgrade snapshot")
		if snapshotErr != nil {
			return model.UpgradeResult{}, fmt.Errorf("pre-upgrade safety snapshot failed; upgrade was not started: %w", snapshotErr)
		}
		snap = x.SnapshotName
	}
	cmd := "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade"
	if strings.EqualFold(r.Distro, "arch") {
		cmd = "pacman -Syu --noconfirm"
	}
	res, e := rt.Runner.Run(ctx, []string{"busybox", "chroot", rt.Config.ChrootBase(), "/bin/bash", "-lc", cmd}, sys.RunOptions{ChrootEnv: true})
	if e != nil {
		return model.UpgradeResult{}, e
	}
	if res.ReturnCode != 0 {
		return model.UpgradeResult{}, fmt.Errorf("upgrade failed: %s", strings.TrimSpace(res.Stderr))
	}
	if progress != nil {
		_ = progress(map[string]any{"phase": "upgrade", "percent": 95, "message": "Upgrade completed"})
	}
	return model.UpgradeResult{Status: "upgraded", Snapshot: snap, NextSteps: []string{"chrootctl --name " + name + " restart", "chrootctl --name " + name + " logs --all"}}, nil
}

func installStringPtr(value string) *string {
	if value == "" {
		return nil
	}
	return &value
}
func installEmptyNil(value string) any {
	if value == "" {
		return nil
	}
	return value
}
