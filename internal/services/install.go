package services

import (
	"chrootctl/internal/install"
	ifactory "chrootctl/internal/install/factory"
	"chrootctl/internal/model"
	sys "chrootctl/internal/system"
	"context"
	"fmt"
	"strings"
)

type InstallService struct{ C *Container }

func (s *InstallService) Distros() []string { return []string{"ubuntu", "arch"} }
func (s *InstallService) Profiles() []string {
	return []string{"minimal", "dev", "xfce4", "plasma", "custom"}
}
func (s *InstallService) Desktops() []string { return []string{"none", "xfce4", "plasma"} }
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
func (s *InstallService) ValidateRequest(req model.InstallRequest) map[string]any {
	blocking := []map[string]string{}
	if req.Distro != "ubuntu" && req.Distro != "arch" {
		blocking = append(blocking, map[string]string{"code": "invalid_distro", "message": "Unsupported distro: " + req.Distro})
	}
	if req.Name == "" {
		blocking = append(blocking, map[string]string{"code": "missing_name", "message": "Install requires a chroot name."})
	}
	if req.Username == "" {
		blocking = append(blocking, map[string]string{"code": "missing_username", "message": "Install requires a target username."})
	}
	arch := req.Arch
	if arch == "" {
		arch = "arm64"
	}
	if arch != "arm64" && arch != "amd64" {
		blocking = append(blocking, map[string]string{"code": "invalid_arch", "message": "Unsupported target arch: " + arch})
	}
	mode := "native"
	if arch != sys.HostArch() {
		mode = "extract-only"
		if sys.CanExecuteForeignArch(arch) {
			mode = "foreign-ready"
		}
	}
	return map[string]any{"ok": len(blocking) == 0, "blocking": blocking, "distro": req.Distro, "name": req.Name, "username": req.Username, "arch": arch, "execution_mode": mode, "requirements": map[string]any{"username_required": true, "default_username": s.C.BaseConfig.Username}}
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
	return map[string]any{"defaults": d, "distros": s.Distros(), "profiles": s.Profiles(), "desktops": s.Desktops(), "users": []map[string]string{}, "cross_arch": s.C.System().CrossArchState()}, nil
}
func (s *InstallService) PreviewInstall(req model.InstallRequest) map[string]any {
	plan := s.ValidateRequest(req)
	plan["kind"] = "install"
	plan["confirm"] = true
	plan["tools"] = req.Tools
	plan["addons"] = req.Addons
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
	plan := s.ValidateRequest(req)
	if ok, _ := plan["ok"].(bool); !ok {
		return model.InstallRunResult{}, fmt.Errorf("invalid install request: %v", plan["blocking"])
	}
	if req.Arch == "" {
		req.Arch = "arm64"
	}
	d, _, e := s.build(ctx, req.Distro, req.Name, req.Username, req.Arch)
	if e != nil {
		return model.InstallRunResult{}, e
	}
	if progress != nil {
		_ = progress(map[string]any{"phase": "validate", "message": "Install request validated", "percent": 8, "plan": plan})
	}
	phaseResults, e := install.Run(ctx, d, install.Request{Phase: phasePtr(req.Phase), Username: req.Username, Desktop: ptrText(req.Desktop), Version: ptrText(req.Version), Release: ptrText(req.Release), Profile: ptrText(req.Profile), ForcePhase: req.ForcePhase, Auto: req.Phase == nil, Resume: req.Resume, Repair: req.Repair})
	if e != nil {
		return model.InstallRunResult{}, e
	}
	if progress != nil {
		_ = progress(map[string]any{"phase": "catalog", "message": "Applying selected tools and addons", "percent": 94})
	}
	result := model.InstallRunResult{ChrootName: req.Name, Distro: req.Distro, Phases: phaseResults, ToolResults: []model.CatalogApplyResult{}, AddonResults: []model.CatalogApplyResult{}}
	tools, e := s.C.Catalog("tool", req.Name).Apply(ctx, req.Tools, progress)
	result.ToolResults = tools
	if e != nil {
		return result, e
	}
	addons, e := s.C.Catalog("addon", req.Name).Apply(ctx, req.Addons, progress)
	result.AddonResults = addons
	if e != nil {
		return result, e
	}
	if progress != nil {
		_ = progress(map[string]any{"phase": "complete", "message": "Install completed", "percent": 100})
	}
	result.NextSteps = []string{"chrootctl --name " + req.Name + " start --login", "chrootctl --name " + req.Name + " logs --all"}
	return result, nil
}
func (s *InstallService) Upgrade(ctx context.Context, name, username string, progress func(any) error) (model.UpgradeResult, error) {
	r, e := s.C.Registry.Get(ctx, name)
	if e != nil || r == nil {
		if e == nil {
			e = fmt.Errorf("no registry record for chroot: %s", name)
		}
		return model.UpgradeResult{}, e
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
	if progress != nil {
		_ = progress(map[string]any{"phase": "upgrade", "percent": 25, "message": "Upgrading chroot"})
	}
	snap := ""
	if s.C.BaseConfig.SnapshotBeforeDestructive {
		if x, e := s.C.Snapshots().Create(ctx, name, "pre-upgrade", "Automatic pre-upgrade snapshot"); e == nil {
			snap = x.SnapshotName
		}
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
