package install

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

type Option struct {
	ID          string `json:"id"`
	Label       string `json:"label"`
	Description string `json:"description,omitempty"`
	Default     bool   `json:"default,omitempty"`
}

type ValidationIssue struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type NormalizedRequest struct {
	Distro            string
	Name              string
	Username          string
	Arch              string
	Preset            string
	Profile           string
	Desktop           string
	Release           string
	Version           string
	Mirror            string
	Phase             string
	ForcePhase        bool
	Resume            bool
	Repair            bool
	OverwriteExisting bool
	Tools             []string
	Addons            []string
}

var packageNamePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9+_.:@-]*$`)

func DistroOptions() []Option {
	return []Option{{ID: "ubuntu", Label: "Ubuntu", Description: "Ubuntu Base rootfs with apt", Default: true}, {ID: "arch", Label: "Arch Linux ARM", Description: "Arch Linux ARM rootfs with pacman"}}
}
func ProfileOptions() []Option {
	return []Option{{ID: "minimal", Label: "Minimal", Description: "Small server-oriented rootfs", Default: true}, {ID: "dev", Label: "Development", Description: "Developer tools and build dependencies"}, {ID: "xfce4", Label: "XFCE desktop", Description: "Desktop profile with XFCE defaults"}, {ID: "plasma", Label: "Plasma desktop", Description: "Desktop profile with KDE Plasma defaults"}, {ID: "custom", Label: "Custom", Description: "No implicit desktop package set"}}
}
func DesktopOptions() []Option {
	return []Option{{ID: "none", Label: "None", Description: "No desktop environment", Default: true}, {ID: "xfce4", Label: "XFCE 4", Description: "Light desktop environment"}, {ID: "plasma", Label: "KDE Plasma", Description: "Full Plasma desktop environment"}}
}
func PresetOptions() []Option {
	return []Option{{ID: "minimal-server", Label: "Minimal server", Description: "minimal profile, no desktop", Default: true}, {ID: "development", Label: "Development", Description: "dev profile, no desktop"}, {ID: "desktop-xfce4", Label: "Desktop XFCE", Description: "xfce4 profile and XFCE desktop"}, {ID: "desktop-plasma", Label: "Desktop Plasma", Description: "plasma profile and Plasma desktop"}, {ID: "custom", Label: "Custom", Description: "Use explicit profile and desktop choices"}}
}
func MirrorOptions(distro string) []Option {
	switch strings.TrimSpace(strings.ToLower(distro)) {
	case "arch":
		return []Option{{ID: "auto", Label: "Auto", Description: "Use the Arch Linux ARM upstream rootfs", Default: true}, {ID: "archlinuxarm", Label: "Arch Linux ARM", Description: "http://os.archlinuxarm.org"}}
	default:
		return []Option{{ID: "auto", Label: "Auto", Description: "Use Ubuntu cdimage release index", Default: true}, {ID: "ubuntu-cdimage", Label: "Ubuntu cdimage", Description: "https://cdimage.ubuntu.com"}}
	}
}
func ArchitectureOptions(distro string) []Option {
	switch strings.TrimSpace(strings.ToLower(distro)) {
	case "arch":
		return []Option{{ID: "arm64", Label: "arm64", Description: "Arch Linux ARM aarch64 rootfs", Default: true}}
	default:
		return []Option{{ID: "arm64", Label: "arm64", Description: "Android/ARM64 target rootfs", Default: true}, {ID: "amd64", Label: "amd64", Description: "x86_64 rootfs for hosts with binfmt/qemu support"}}
	}
}
func OptionIDs(options []Option) []string {
	out := make([]string, 0, len(options))
	for _, option := range options {
		out = append(out, option.ID)
	}
	return out
}
func validOption(id string, options []Option) bool {
	for _, option := range options {
		if id == option.ID {
			return true
		}
	}
	return false
}
func NormalizeInstallShape(distro, name, username, arch, preset, profile, desktop, release, version, mirror, phase string, forcePhase, resume, repair, overwriteExisting bool, tools, addons []string, defaultUsername, defaultArch string) (NormalizedRequest, []ValidationIssue) {
	out := NormalizedRequest{
		Distro:            strings.TrimSpace(strings.ToLower(distro)),
		Name:              strings.TrimSpace(name),
		Username:          strings.TrimSpace(username),
		Arch:              strings.TrimSpace(strings.ToLower(arch)),
		Preset:            strings.TrimSpace(strings.ToLower(preset)),
		Profile:           strings.TrimSpace(strings.ToLower(profile)),
		Desktop:           strings.TrimSpace(strings.ToLower(desktop)),
		Release:           strings.TrimSpace(release),
		Version:           strings.TrimSpace(version),
		Mirror:            strings.TrimSpace(strings.ToLower(mirror)),
		Phase:             strings.TrimSpace(strings.ToLower(phase)),
		ForcePhase:        forcePhase,
		Resume:            resume,
		Repair:            repair,
		OverwriteExisting: overwriteExisting,
		Tools:             uniqueNonEmpty(tools),
		Addons:            uniqueNonEmpty(addons),
	}
	if out.Distro == "" {
		out.Distro = "ubuntu"
	}
	if out.Name == "" {
		out.Name = out.Distro
	}
	if out.Username == "" {
		out.Username = defaultUsername
	}
	if out.Arch == "" {
		out.Arch = defaultArch
	}
	if out.Arch == "" {
		out.Arch = "arm64"
	}
	if out.Preset == "" {
		out.Preset = "minimal-server"
	}
	if out.Mirror == "" {
		out.Mirror = "auto"
	}
	if out.Preset != "custom" {
		switch out.Preset {
		case "minimal-server":
			if out.Profile == "" {
				out.Profile = "minimal"
			}
			if out.Desktop == "" || out.Desktop == "auto" {
				out.Desktop = "none"
			}
		case "development", "recovery-debug":
			if out.Profile == "" {
				out.Profile = "dev"
			}
			if out.Desktop == "" || out.Desktop == "auto" {
				out.Desktop = "none"
			}
		case "desktop-xfce", "desktop-xfce4":
			out.Preset = "desktop-xfce4"
			if out.Profile == "" {
				out.Profile = "xfce4"
			}
			if out.Desktop == "" || out.Desktop == "auto" {
				out.Desktop = "xfce4"
			}
		case "desktop-plasma":
			if out.Profile == "" {
				out.Profile = "plasma"
			}
			if out.Desktop == "" || out.Desktop == "auto" {
				out.Desktop = "plasma"
			}
		}
	}
	if out.Profile == "" {
		out.Profile = "minimal"
	}
	if out.Desktop == "" || out.Desktop == "auto" {
		if d, ok := ProfileDefaultDesktop[out.Profile]; ok {
			out.Desktop = d
		} else {
			out.Desktop = "none"
		}
	}
	issues := []ValidationIssue{}
	if !validOption(out.Distro, DistroOptions()) {
		issues = append(issues, ValidationIssue{Code: "invalid_distro", Message: "Unsupported distro: " + out.Distro})
	}
	if !validOption(out.Arch, ArchitectureOptions(out.Distro)) {
		issues = append(issues, ValidationIssue{Code: "invalid_arch", Message: fmt.Sprintf("Unsupported target architecture %q for distro %q", out.Arch, out.Distro)})
	}
	if !validOption(out.Profile, ProfileOptions()) {
		issues = append(issues, ValidationIssue{Code: "invalid_profile", Message: "Unsupported install profile: " + out.Profile})
	}
	if !validOption(out.Desktop, DesktopOptions()) {
		issues = append(issues, ValidationIssue{Code: "invalid_desktop", Message: "Unsupported desktop: " + out.Desktop})
	}
	if out.Profile == "minimal" && out.Desktop != "none" {
		issues = append(issues, ValidationIssue{Code: "profile_desktop_conflict", Message: "Minimal profile does not allow desktop installation; choose profile xfce4/plasma/custom or desktop none."})
	}
	if !validOption(out.Mirror, MirrorOptions(out.Distro)) {
		issues = append(issues, ValidationIssue{Code: "invalid_mirror", Message: "Unsupported mirror identifier: " + out.Mirror})
	}
	if out.Phase != "" && !validPhase(out.Phase) {
		issues = append(issues, ValidationIssue{Code: "invalid_phase", Message: "Unsupported install phase: " + out.Phase})
	}
	return out, issues
}
func validPhase(phase string) bool {
	for _, p := range Phases {
		if string(p) == phase {
			return true
		}
	}
	return false
}
func InstallPhasesFrom(start string) []string {
	p := Extract
	if start != "" && validPhase(start) {
		p = Phase(start)
	}
	i := PhaseIndex(p)
	if i < 0 {
		i = 0
	}
	out := make([]string, 0, len(Phases)-i)
	for _, phase := range Phases[i:] {
		out = append(out, string(phase))
	}
	return out
}
func ValidatePackageNames(pkgs []string) ([]string, error) {
	out := uniqueNonEmpty(pkgs)
	invalid := []string{}
	for _, pkg := range out {
		if !packageNamePattern.MatchString(pkg) {
			invalid = append(invalid, pkg)
		}
	}
	if len(invalid) > 0 {
		sort.Strings(invalid)
		return nil, fmt.Errorf("invalid package name(s): %s", strings.Join(invalid, ", "))
	}
	return out, nil
}
func ShellQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'" }
func ShellJoin(values []string) string {
	quoted := make([]string, 0, len(values))
	for _, value := range values {
		quoted = append(quoted, ShellQuote(value))
	}
	return strings.Join(quoted, " ")
}
func uniqueNonEmpty(values []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		out = append(out, value)
	}
	return out
}
