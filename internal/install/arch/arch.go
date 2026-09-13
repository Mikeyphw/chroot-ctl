package arch

import (
	"chrootctl/internal/install"
	"chrootctl/internal/integrity"
	"chrootctl/internal/model"
	sys "chrootctl/internal/system"
	"context"
	"errors"
	"os"
	"path/filepath"
)

type Installer struct {
	*install.Base
	Download func(string, string) error
}

const RootFSURL = "http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz"

var basePackages = []string{"sudo", "nano", "vim", "git", "curl", "wget", "which", "less"}
var devPackages = []string{"base-devel", "python", "python-pip", "pkgconf"}

func New(base *install.Base) *Installer           { return &Installer{Base: base} }
func (i *Installer) BaseInstaller() *install.Base { return i.Base }
func RootFSURLForArch(arch string) (string, error) {
	switch arch {
	case "", "arm64":
		return RootFSURL, nil
	default:
		return "", errors.New("arch installer currently supports only arm64/aarch64 rootfs")
	}
}
func (i *Installer) InferPhaseFromFilesystem() install.Phase {
	b := i.Config.ChrootBase()
	if _, e := os.Stat(filepath.Join(b, "etc/os-release")); e != nil {
		return install.Extract
	}
	if !i.ReadyForBootstrap() {
		return install.Extract
	}
	if _, e := os.Stat(filepath.Join(b, "etc/sudoers.d", i.Config.Username)); e != nil {
		return install.Extract
	}
	if _, e := os.Stat(filepath.Join(b, "usr/share/X11")); e != nil {
		return install.Bootstrap
	}
	return install.Finalize
}
func (i *Installer) ReadyForBootstrap() bool {
	_, e := os.Stat(filepath.Join(i.Config.ChrootBase(), "usr/bin/pacman"))
	return e == nil
}
func (i *Installer) RunPhaseExtract(ctx context.Context, version, release string, force bool) (model.InstallExtractResult, error) {
	if e := i.Runner.RequireRoot(); e != nil {
		return model.InstallExtractResult{}, e
	}
	if e := i.AssertPhaseAllowed(ctx, install.Extract, force); e != nil {
		return model.InstallExtractResult{}, e
	}
	url, e := RootFSURLForArch(i.Config.TargetArch)
	if e != nil {
		return model.InstallExtractResult{}, e
	}
	name := filepath.Base(url)
	if i.Runner.DryRun {
		_, e := i.Runner.Run(ctx, []string{"curl", "--fail", "--location", url, "-o", name}, sys.RunOptions{NoCapture: true})
		if e != nil {
			return model.InstallExtractResult{}, e
		}
	} else {
		if i.Download == nil {
			return model.InstallExtractResult{}, errors.New("download function is not configured")
		}
		work, e := i.NewWorkDir("download")
		if e != nil {
			return model.InstallExtractResult{}, e
		}
		defer os.RemoveAll(work)
		stage, e := i.NewWorkDir("rootfs")
		if e != nil {
			return model.InstallExtractResult{}, e
		}
		defer os.RemoveAll(stage)
		tar := filepath.Join(work, name)
		sig := tar + ".sig"
		if e = i.Download(url, tar); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = i.Download(url+".sig", sig); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = integrity.VerifyDetachedSignature(ctx, i.Runner, tar, sig, integrity.ArchLinuxARMSigningFingerprint, ""); e != nil {
			return model.InstallExtractResult{}, e
		}
		if _, e = i.Runner.Run(ctx, []string{"bsdtar", "-xpf", tar, "-C", stage}, sys.RunOptions{NoCapture: true}); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = i.PromoteStagedRootFS(ctx, stage); e != nil {
			return model.InstallExtractResult{}, e
		}
	}
	for _, rel := range []string{"dev/pts", "dev/shm", "proc", "sys", "tmp", "media/sdcard", "home/" + i.Config.Username} {
		if !i.Runner.DryRun {
			_ = os.MkdirAll(filepath.Join(i.Config.ChrootBase(), rel), 0o755)
		}
	}
	e = i.MarkPhase(ctx, install.Extract, false, "latest", "rolling", map[string]any{"tarball": name, "url": url, "requested_url": url, "mirror": i.MirrorSelection, "integrity": "openpgp", "signing_fingerprint": integrity.ArchLinuxARMSigningFingerprint})
	return model.InstallExtractResult{Version: "latest", Release: "rolling", Tarball: name, Phase: "extract"}, e
}
func unique(xs []string) []string {
	m := map[string]bool{}
	o := []string{}
	for _, x := range xs {
		if !m[x] {
			m[x] = true
			o = append(o, x)
		}
	}
	return o
}
func (i *Installer) RunPhaseBootstrap(ctx context.Context, u, p string, f bool) (model.InstallBootstrapResult, error) {
	if e := i.Runner.RequireRoot(); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.EnsureExecutionSupported(); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.AssertPhaseAllowed(ctx, install.Bootstrap, f); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.EnsureCommonBootstrapPrereqs(ctx); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.RequireChrootCommands(ctx, "pacman"); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	for _, cmd := range []string{`sed -i 's/^CheckSpace/#CheckSpace/' /etc/pacman.conf || true`, `pacman-key --init || true`, `pacman-key --populate archlinuxarm || true`, `pacman-key --refresh-keys || true`, `pacman -Syu --noconfirm`} {
		if _, e := i.ChrootShell(ctx, cmd, false); e != nil {
			return model.InstallBootstrapResult{}, e
		}
	}
	pkgs := append([]string{}, basePackages...)
	if p == "dev" {
		pkgs = append(pkgs, devPackages...)
	}
	var e error
	pkgs, e = install.ValidatePackageNames(append(pkgs, i.Config.ExtraPackages...))
	if e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if len(pkgs) > 0 {
		if _, e := i.ChrootShell(ctx, "pacman -S --noconfirm "+install.ShellJoin(pkgs), false); e != nil {
			return model.InstallBootstrapResult{}, e
		}
	}
	user := install.ShellQuote(u)
	cmds := []string{
		"getent group storage >/dev/null || groupadd storage",
		"getent group wheel >/dev/null || groupadd wheel",
		"getent group " + user + " >/dev/null || groupadd " + user,
		"id -u " + user + " >/dev/null 2>&1 || useradd -m -s /bin/bash -g " + user + " -G wheel,storage " + user,
		"printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' " + user + " > /etc/sudoers.d/" + user + " && chmod 440 /etc/sudoers.d/" + user,
	}
	for _, cmd := range cmds {
		if _, e := i.ChrootShell(ctx, cmd, false); e != nil {
			return model.InstallBootstrapResult{}, e
		}
	}
	if e := i.MarkPhase(ctx, install.Bootstrap, false, "", "", map[string]any{"username": u, "profile": p}); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	return model.InstallBootstrapResult{Username: u, Profile: p, Phase: "bootstrap"}, nil
}
func (i *Installer) RunPhaseDesktop(ctx context.Context, d, p string, f bool) (model.InstallDesktopResult, error) {
	if e := i.Runner.RequireRoot(); e != nil {
		return model.InstallDesktopResult{}, e
	}
	if e := i.EnsureExecutionSupported(); e != nil {
		return model.InstallDesktopResult{}, e
	}
	if e := i.AssertPhaseAllowed(ctx, install.Desktop, f); e != nil {
		return model.InstallDesktopResult{}, e
	}
	snap, e := i.CreateSnapshot(ctx, "desktop")
	if e != nil {
		return model.InstallDesktopResult{}, e
	}
	pkg := map[string]string{"xfce4": "xfce4 xfce4-terminal", "plasma": "plasma-meta konsole", "none": ""}[d]
	if d != "none" && pkg == "" {
		return model.InstallDesktopResult{}, errors.New("unsupported desktop: " + d)
	}
	if pkg != "" {
		if _, e = i.ChrootShell(ctx, "pacman -S --noconfirm "+pkg, false); e != nil {
			return model.InstallDesktopResult{}, e
		}
	}
	e = i.MarkPhase(ctx, install.Desktop, false, "", "", map[string]any{"desktop": d, "desktop_snapshot": snap, "profile": p})
	return model.InstallDesktopResult{Desktop: d, Snapshot: snap, Profile: p, Phase: "desktop"}, e
}
func (i *Installer) RunPhaseFinalize(ctx context.Context, u string, f bool) (model.InstallFinalizeResult, error) {
	return i.Finalize(ctx, u, f)
}
