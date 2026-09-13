package install

import (
	"strings"
	"testing"
)

func TestCHR11InstallPolicyUsesBackendOptionIds(t *testing.T) {
	if got := OptionIDs(DistroOptions()); strings.Join(got, ",") != "ubuntu,arch" {
		t.Fatalf("unexpected distros: %v", got)
	}
	if got := OptionIDs(ArchitectureOptions("arch")); strings.Join(got, ",") != "arm64" {
		t.Fatalf("arch must expose only arm64 to avoid amd64/aarch64 mismatch: %v", got)
	}
	if got := OptionIDs(ProfileOptions()); !contains(got, "dev") || contains(got, "developer") {
		t.Fatalf("profile ids must match backend contract exactly: %v", got)
	}
	if got := OptionIDs(DesktopOptions()); !contains(got, "xfce4") || contains(got, "xfce") || contains(got, "lxqt") {
		t.Fatalf("desktop ids must match backend contract exactly: %v", got)
	}
}

func TestCHR11NormalizePresetAndRejectInvalidShape(t *testing.T) {
	n, issues := NormalizeInstallShape("ubuntu", "", "mike", "arm64", "desktop-xfce", "", "", "", "", "", "", false, false, false, false, nil, nil, "mike", "arm64")
	if len(issues) != 0 {
		t.Fatalf("unexpected issues: %+v", issues)
	}
	if n.Preset != "desktop-xfce4" || n.Profile != "xfce4" || n.Desktop != "xfce4" || n.Name != "ubuntu" {
		t.Fatalf("unexpected normalized request: %+v", n)
	}
	_, issues = NormalizeInstallShape("debian", "demo", "mike", "amd64", "minimal-server", "minimal", "none", "", "", "auto", "", false, false, false, false, nil, nil, "mike", "arm64")
	if !hasIssue(issues, "invalid_distro") {
		t.Fatalf("expected invalid_distro issue, got %+v", issues)
	}
	_, issues = NormalizeInstallShape("arch", "demo", "mike", "amd64", "minimal-server", "minimal", "none", "", "", "auto", "", false, false, false, false, nil, nil, "mike", "arm64")
	if !hasIssue(issues, "invalid_arch") {
		t.Fatalf("expected invalid_arch issue, got %+v", issues)
	}
}

func TestCHR11PackageValidationShellQuotesExtraPackages(t *testing.T) {
	pkgs, err := ValidatePackageNames([]string{"git", "python3-pip", "git"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(pkgs, ",") != "git,python3-pip" {
		t.Fatalf("unexpected package list: %v", pkgs)
	}
	if got := ShellJoin(pkgs); got != "'git' 'python3-pip'" {
		t.Fatalf("unexpected shell join: %s", got)
	}
	if _, err = ValidatePackageNames([]string{"ok", "bad;rm"}); err == nil {
		t.Fatal("expected invalid package name to be rejected")
	}
}

func hasIssue(issues []ValidationIssue, code string) bool {
	for _, issue := range issues {
		if issue.Code == code {
			return true
		}
	}
	return false
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
