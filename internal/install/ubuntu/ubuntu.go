package ubuntu

import (
	"chrootctl/internal/install"
	"chrootctl/internal/integrity"
	"chrootctl/internal/model"
	sys "chrootctl/internal/system"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type Installer struct {
	*install.Base
	FetchText func(string) (string, error)
	Download  func(string, string) error
}

const ReleaseIndexURL = "https://cdimage.ubuntu.com/ubuntu-base/releases/"

var prereq = []string{"passwd", "login", "libc-bin", "sudo"}
var basePackages = []string{"nano", "vim", "net-tools", "git", "locales", "dbus-x11", "curl", "wget"}
var devPackages = []string{"build-essential", "pkg-config", "python3", "python3-pip"}

func New(base *install.Base) *Installer           { return &Installer{Base: base} }
func (i *Installer) BaseInstaller() *install.Base { return i.Base }

var href = regexp.MustCompile(`href=["']([^"']+)["']`)

func ParseReleaseIndex(html string) []install.ReleaseRef {
	seen := map[string]install.ReleaseRef{}
	for _, m := range href.FindAllStringSubmatch(html, -1) {
		x := strings.Trim(m[1], "/")
		digits := strings.ReplaceAll(x, ".", "")
		numeric := digits != "" && strings.Trim(digits, "0123456789") == ""
		alpha := x != ""
		for _, r := range x {
			if !(r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z') {
				alpha = false
				break
			}
		}
		if numeric || alpha {
			seen[x] = install.ReleaseRef{Label: x, URL: ReleaseIndexURL + x + "/release/"}
		}
	}
	keys := make([]string, 0, len(seen))
	for k := range seen {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make([]install.ReleaseRef, 0, len(keys))
	for _, k := range keys {
		out = append(out, seen[k])
	}
	return out
}
func ResolveTarball(html, arch, baseURL string) (string, string, error) {
	suffix := map[string]string{"arm64": "-base-arm64.tar.gz", "amd64": "-base-amd64.tar.gz"}[arch]
	if suffix == "" {
		return "", "", fmt.Errorf("unsupported ubuntu target arch: %s", arch)
	}
	type candidate struct {
		name    string
		version []int
	}
	candidates := make([]candidate, 0)
	seen := map[string]bool{}
	for _, m := range href.FindAllStringSubmatch(html, -1) {
		name := filepath.Base(strings.TrimSpace(m[1]))
		if seen[name] || !strings.HasPrefix(name, "ubuntu-base-") || !strings.HasSuffix(name, suffix) {
			continue
		}
		versionText := strings.TrimSuffix(strings.TrimPrefix(name, "ubuntu-base-"), suffix)
		version, ok := numericVersion(versionText)
		if !ok {
			continue
		}
		seen[name] = true
		candidates = append(candidates, candidate{name: name, version: version})
	}
	if len(candidates) == 0 {
		return "", "", fmt.Errorf("could not find ubuntu-base %s tarball under %s", arch, baseURL)
	}
	sort.SliceStable(candidates, func(a, b int) bool {
		if c := compareNumericVersion(candidates[a].version, candidates[b].version); c != 0 {
			return c > 0
		}
		return candidates[a].name > candidates[b].name
	})
	name := candidates[0].name
	return name, baseURL + name, nil
}

func numericVersion(value string) ([]int, bool) {
	parts := strings.Split(value, ".")
	if len(parts) < 2 {
		return nil, false
	}
	out := make([]int, 0, len(parts))
	for _, part := range parts {
		if part == "" {
			return nil, false
		}
		n, err := strconv.Atoi(part)
		if err != nil || n < 0 {
			return nil, false
		}
		out = append(out, n)
	}
	return out, true
}

func compareNumericVersion(a, b []int) int {
	n := len(a)
	if len(b) > n {
		n = len(b)
	}
	for idx := 0; idx < n; idx++ {
		av, bv := 0, 0
		if idx < len(a) {
			av = a[idx]
		}
		if idx < len(b) {
			bv = b[idx]
		}
		if av < bv {
			return -1
		}
		if av > bv {
			return 1
		}
	}
	return 0
}

func tarballVersion(name, arch string) (string, bool) {
	suffix := tarballSuffixForArch(arch)
	if suffix == "" || !strings.HasPrefix(name, "ubuntu-base-") || !strings.HasSuffix(name, suffix) {
		return "", false
	}
	version := strings.TrimSuffix(strings.TrimPrefix(name, "ubuntu-base-"), suffix)
	if _, ok := numericVersion(version); !ok {
		return "", false
	}
	return version, true
}
func (i *Installer) ListVersions() (out []install.ReleaseRef, err error) {
	if i.FetchText == nil {
		return nil, errors.New("fetch function is not configured")
	}
	html, e := i.FetchText(ReleaseIndexURL)
	if e != nil {
		return nil, e
	}
	return ParseReleaseIndex(html), nil
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
	if _, e := os.Stat(filepath.Join(b, "etc/apt/preferences.d/nosnap.pref")); e != nil {
		return install.Desktop
	}
	return install.Finalize
}
func (i *Installer) ReadyForBootstrap() bool {
	_, e := os.Stat(filepath.Join(i.Config.ChrootBase(), "usr/bin/apt"))
	return e == nil
}
func (i *Installer) resolveRelease(version, release string) (install.ReleaseRef, error) {
	refs, e := i.ListVersions()
	if e != nil {
		return install.ReleaseRef{}, e
	}
	m := map[string]install.ReleaseRef{}
	for _, r := range refs {
		m[r.Label] = r
	}
	for _, k := range []string{version, release, "24.04", "noble"} {
		if r, ok := m[k]; ok && k != "" {
			return r, nil
		}
	}
	return install.ReleaseRef{}, errors.New("could not resolve ubuntu release; pass --version or --release")
}
func unique(xs []string) []string {
	seen := map[string]bool{}
	o := []string{}
	for _, x := range xs {
		if !seen[x] {
			seen[x] = true
			o = append(o, x)
		}
	}
	return o
}
func (i *Installer) RunPhaseExtract(ctx context.Context, version, release string, force bool) (model.InstallExtractResult, error) {
	if e := i.Runner.RequireRoot(); e != nil {
		return model.InstallExtractResult{}, e
	}
	if e := i.AssertPhaseAllowed(ctx, install.Extract, force); e != nil {
		return model.InstallExtractResult{}, e
	}
	ref, e := i.resolveRelease(version, release)
	if e != nil {
		return model.InstallExtractResult{}, e
	}
	if i.FetchText == nil {
		return model.InstallExtractResult{}, errors.New("fetch function is not configured")
	}
	html, e := i.FetchText(ref.URL)
	if e != nil {
		return model.InstallExtractResult{}, e
	}
	name, url, e := ResolveTarball(html, i.Config.TargetArch, ref.URL)
	if e != nil {
		return model.InstallExtractResult{}, e
	}
	if i.Runner.DryRun {
		_, e = i.Runner.Run(ctx, []string{"curl", "--fail", "--location", url, "-o", name}, sys.RunOptions{NoCapture: true})
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
		sums := filepath.Join(work, "SHA256SUMS")
		sig := filepath.Join(work, "SHA256SUMS.gpg")
		keyring := filepath.Join(work, "ubuntu-archive-keyring.gpg")
		if e = i.Download(url, tar); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = i.Download(ref.URL+"SHA256SUMS", sums); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = i.Download(ref.URL+"SHA256SUMS.gpg", sig); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = i.Download(integrity.UbuntuSigningKeyringURL, keyring); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = integrity.VerifyDetachedSignatureWithKeyringFile(sums, sig, keyring, integrity.UbuntuSigningFingerprint); e != nil {
			return model.InstallExtractResult{}, e
		}
		sum, e := integrity.ChecksumFromManifest(sums, name)
		if e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = integrity.VerifySHA256(tar, sum); e != nil {
			return model.InstallExtractResult{}, e
		}
		if _, e = i.Runner.Run(ctx, []string{"tar", "xpf", tar, "--numeric-owner", "-C", stage}, sys.RunOptions{NoCapture: true}); e != nil {
			return model.InstallExtractResult{}, e
		}
		if e = i.PromoteStagedRootFS(ctx, stage); e != nil {
			return model.InstallExtractResult{}, e
		}
	}
	for _, rel := range []string{"dev/pts", "dev/shm", "proc", "sys", "sdcard", "tmp", "home/" + i.Config.Username} {
		if !i.Runner.DryRun {
			_ = os.MkdirAll(filepath.Join(i.Config.ChrootBase(), rel), 0o755)
		}
	}
	requestedVersion, requestedRelease := version, release
	resolvedVersion, ok := tarballVersion(name, i.Config.TargetArch)
	if !ok {
		resolvedVersion = version
		if resolvedVersion == "" {
			resolvedVersion = ref.Label
		}
	}
	resolvedRelease := release
	if resolvedRelease == "" {
		resolvedRelease = ref.Label
	}
	e = i.MarkPhase(ctx, install.Extract, false, resolvedVersion, resolvedRelease, map[string]any{
		"tarball": name, "url": url, "requested_url": url, "mirror": i.MirrorSelection,
		"integrity": "openpgp+sha256", "signing_fingerprint": integrity.UbuntuSigningFingerprint,
		"requested_version": requestedVersion, "requested_release": requestedRelease, "resolved_release": ref.Label,
	})
	return model.InstallExtractResult{Version: resolvedVersion, Release: resolvedRelease, Tarball: name, Phase: "extract"}, e
}
func (i *Installer) RunPhaseBootstrap(ctx context.Context, username, profile string, force bool) (model.InstallBootstrapResult, error) {
	if e := i.Runner.RequireRoot(); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.EnsureExecutionSupported(); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.AssertPhaseAllowed(ctx, install.Bootstrap, force); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.EnsureCommonBootstrapPrereqs(ctx); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if e := i.RequireChrootCommands(ctx, "apt"); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if _, e := i.ChrootShell(ctx, "apt update", false); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	pkgs := append([]string{}, prereq...)
	pkgs = append(pkgs, basePackages...)
	if profile == "dev" {
		pkgs = append(pkgs, devPackages...)
	}
	pkgs = append(pkgs, i.Config.ExtraPackages...)
	var e error
	pkgs, e = install.ValidatePackageNames(pkgs)
	if e != nil {
		return model.InstallBootstrapResult{}, e
	}
	if _, e := i.ChrootShell(ctx, "DEBIAN_FRONTEND=noninteractive apt install -y "+install.ShellJoin(pkgs), false); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	u := install.ShellQuote(username)
	cmds := []string{
		"getent group storage >/dev/null || groupadd storage",
		"getent group wheel >/dev/null || groupadd wheel",
		"getent group " + u + " >/dev/null || groupadd " + u,
		"id -u " + u + " >/dev/null 2>&1 || useradd -m -s /bin/bash -g " + u + " -G sudo,storage " + u,
		"printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' " + u + " > /etc/sudoers.d/" + u + " && chmod 440 /etc/sudoers.d/" + u,
	}
	for _, c := range cmds {
		if _, e := i.ChrootShell(ctx, c, false); e != nil {
			return model.InstallBootstrapResult{}, e
		}
	}
	if e := i.MarkPhase(ctx, install.Bootstrap, false, "", "", map[string]any{"username": username, "profile": profile}); e != nil {
		return model.InstallBootstrapResult{}, e
	}
	return model.InstallBootstrapResult{Username: username, Profile: profile, Phase: "bootstrap"}, nil
}
func (i *Installer) RunPhaseDesktop(ctx context.Context, desktop, profile string, force bool) (model.InstallDesktopResult, error) {
	if e := i.Runner.RequireRoot(); e != nil {
		return model.InstallDesktopResult{}, e
	}
	if e := i.EnsureExecutionSupported(); e != nil {
		return model.InstallDesktopResult{}, e
	}
	if e := i.AssertPhaseAllowed(ctx, install.Desktop, force); e != nil {
		return model.InstallDesktopResult{}, e
	}
	snap, e := i.CreateSnapshot(ctx, "desktop")
	if e != nil {
		return model.InstallDesktopResult{}, e
	}
	pkgs := map[string][]string{"xfce4": {"xfce4", "xfce4-terminal", "dbus-x11", "adwaita-icon-theme"}, "plasma": {"plasma-desktop", "konsole", "dbus-x11", "breeze-icon-theme"}, "none": {}}[desktop]
	if pkgs == nil {
		return model.InstallDesktopResult{}, fmt.Errorf("unsupported desktop: %s", desktop)
	}
	if len(pkgs) > 0 {
		if _, e = i.ChrootShell(ctx, "DEBIAN_FRONTEND=noninteractive apt install -y "+install.ShellJoin(pkgs), false); e != nil {
			return model.InstallDesktopResult{}, e
		}
	}
	if e = i.MarkPhase(ctx, install.Desktop, false, "", "", map[string]any{"desktop": desktop, "desktop_snapshot": snap, "profile": profile}); e != nil {
		return model.InstallDesktopResult{}, e
	}
	return model.InstallDesktopResult{Desktop: desktop, Snapshot: snap, Profile: profile, Phase: "desktop"}, nil
}
func (i *Installer) RunPhaseFinalize(ctx context.Context, u string, f bool) (model.InstallFinalizeResult, error) {
	return i.Finalize(ctx, u, f)
}
