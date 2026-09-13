package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateInstallerUpgradeReconstruction is the executable CHR11 source seal.
// It keeps install form options, distro fetch wiring, phase/resume state,
// upgrade preflight, and Android wizard choices aligned with the native Go
// backend instead of stale UI fallbacks or ad-hoc shell shortcuts.
func ValidateInstallerUpgradeReconstruction(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR11 read %s: %w", rel, err)
		}
		return string(b), nil
	}
	mustContain := func(rel string, tokens ...string) error {
		text, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if !strings.Contains(text, token) {
				return fmt.Errorf("CHR11 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	if err := mustContain("internal/install/policy.go",
		"func DistroOptions() []Option",
		"func ArchitectureOptions(distro string) []Option",
		"func NormalizeInstallShape(",
		"func ValidatePackageNames(",
		"func ShellJoin(values []string) string",
	); err != nil {
		return err
	}
	if err := mustContain("internal/install/base.go",
		"AllowExistingRootfsReplace",
		"DeferInstalledFinalization",
		"Progress",
		"func(ProgressEvent) error",
		"chroot registry record missing after install transaction seed",
		"ApplyConfiguredLocale",
		"RunPostInstallHook",
		"pending-catalog",
	); err != nil {
		return err
	}
	if err := mustContain("internal/install/factory/factory.go",
		"i.FetchText = fetchText",
		"i.Download = download",
		"curl", "--retry",
	); err != nil {
		return err
	}
	if err := mustContain("internal/install/arch/arch.go",
		"RootFSURLForArch",
		"supports only arm64",
		"useradd -m -s /bin/bash",
		"/etc/sudoers.d/",
		"install.ValidatePackageNames",
	); err != nil {
		return err
	}
	if err := mustContain("internal/install/ubuntu/ubuntu.go",
		"install.ValidatePackageNames",
		"install.ShellJoin(pkgs)",
		"/etc/sudoers.d/",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/install.go",
		"install.DistroOptions()",
		"install.ArchitectureOptions(chosenDistro)",
		"install.PresetOptions()",
		"install.ProfileOptions()",
		"install.DesktopOptions()",
		"checkExistingTarget",
		"overwrite_existing",
		"progress_milestones",
		"EnsureCommonBootstrapPrereqs(ctx)",
		"upgrade requires an installed finalized chroot",
		"upgrade target mismatch",
		"MarkPhase(ctx, install.Finalize, true",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/preview.go",
		"not_finalized",
		"unsupported_distro",
		"target_identity",
		"managed pre-upgrade snapshot",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/backend.go",
		"OverwriteExisting",
		"overwrite_existing",
		"stringPtr(\"minimal\")",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt",
		"overwriteExisting",
		"resume: Boolean",
		"repair: Boolean",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
		"overwrite_existing",
		"value.firstString(\"id\", \"name\", \"label\")",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/install/InstallScreen.kt",
		"listOf(\"ubuntu\", \"arch\")",
		"listOf(\"minimal\", \"dev\", \"xfce4\", \"plasma\", \"custom\")",
		"listOf(\"none\", \"xfce4\", \"plasma\")",
		"Overwrite existing",
		"Resume / repair",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/WorkflowUxPolicy.kt",
		"draft.distro in setOf(\"ubuntu\", \"arch\")",
		"if (draft.distro == \"arch\") setOf(\"arm64\")",
	); err != nil {
		return err
	}
	if err := mustContain("migration/contracts/v1/cli.json",
		"--overwrite-existing",
		"Explicitly allow replacing an existing rootfs directory",
	); err != nil {
		return err
	}
	if err := mustContain("migration/contracts/v1/bridge.json",
		"overwrite_existing",
		"overwriteExisting",
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR11_INSTALLER_UPGRADE_RECONSTRUCTION.md",
		"Installer & upgrade reconstruction",
		"Android form parity",
		"upgrade preflight",
		"pending-catalog",
	); err != nil {
		return err
	}
	raw, err := os.ReadFile(filepath.Join(root, "docs", "audit", "roadmap-coverage.json"))
	if err != nil {
		return fmt.Errorf("CHR11 read roadmap coverage: %w", err)
	}
	var coverage auditCoverage
	if err := json.Unmarshal(raw, &coverage); err != nil {
		return fmt.Errorf("CHR11 parse roadmap coverage: %w", err)
	}
	chr11 := map[string]bool{"D20": true, "D21": true, "D22": true, "U028": true, "U029": true, "U030": true, "U031": true, "U032": true, "U033": true, "U034": true, "U035": true, "U036": true, "U133": true, "U134": true, "U135": true, "U136": true, "U137": true, "U138": true, "U139": true, "U140": true, "U141": true, "U142": true, "U143": true, "U144": true, "U145": true, "U146": true, "U147": true, "U148": true, "U177": true, "U224": true}
	seen := map[string]bool{}
	sources := 0
	for _, finding := range coverage.CanonicalFindings {
		if !chr11[finding.ID] {
			continue
		}
		if finding.OwnerOverlay != "CHR11" || finding.Status == "planned" {
			return fmt.Errorf("CHR11 finding %s is not marked implemented", finding.ID)
		}
		seen[finding.ID] = true
		sources += len(finding.SourceFindings)
	}
	if len(seen) != len(chr11) {
		return fmt.Errorf("CHR11 implemented coverage=%d, want %d", len(seen), len(chr11))
	}
	if sources != 41 {
		return fmt.Errorf("CHR11 source-manifestation coverage=%d, want 41", sources)
	}
	return nil
}
