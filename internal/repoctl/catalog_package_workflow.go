package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateCatalogPackageWorkflow keeps CHR13 executable instead of prose-only.
// It seals catalog/package invariants that were found in the audit: blocked
// host-managed sync-uid, stable/trusted external catalog reads, real risk state
// exposure, non-destructive Arch package scripts, Android target/category UX,
// and truthful package inventory truncation.
func ValidateCatalogPackageWorkflow(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR13 read %s: %w", rel, err)
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
				return fmt.Errorf("CHR13 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	mustNotContain := func(rel string, tokens ...string) error {
		text, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if strings.Contains(text, token) {
				return fmt.Errorf("CHR13 %s still contains forbidden token %q", rel, token)
			}
		}
		return nil
	}

	if err := mustNotContain("go.mod", "replace github.com/mattn/go-sqlite3 => /mnt/data/go-sqlite3-stub"); err != nil {
		return err
	}

	if err := mustContain("internal/catalog/catalog.go",
		"var supportedSuffix = map[string]bool{\".sh\": true}",
		"ScriptSHA256",
		"RiskLevel",
		"RequiresConfirmation",
		"func readStable(path, label string)",
		"func safeExternalParentChain(path, label string)",
		"func (e Entry) IsBlocked() bool",
		"func (e Entry) WithMetadataState(meta map[string]any) Entry",
		"entry.IsBlocked()",
		"script_sha256",
		"requires_confirmation",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/catalog.go",
		"func (s *CatalogService) EnrichEntries",
		"func (s *CatalogService) EntryState",
		"entry.IsBlocked()",
		"risk_level",
		"script_sha256",
		"requires_confirmation",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/backend.go",
		"scriptSha256",
		"script_sha256",
		"riskLevel",
		"risk_level",
		"requiresConfirmation",
		"requires_confirmation",
		"entry_blocked",
		"preflight_unavailable",
		"PackageInventory(ctx, n, lim)",
	); err != nil {
		return err
	}
	if err := mustContain("internal/model/models.go",
		"type PackageInventoryResult struct",
		"Truncated bool",
		"json:\"truncated\"",
		"ScriptSHA256",
		"json:\"script_sha256\"",
		"RiskLevel",
		"json:\"risk_level\"",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/chroots.go",
		"model.PackageInventoryResult",
		"Count: total",
		"Truncated: truncated",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt",
		"val riskLevel: String",
		"val scriptSha256: String",
		"val requiresConfirmation: Boolean",
		"val truncated: Boolean",
		"val limit: Int = 0",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
		"risk_level",
		"script_sha256",
		"requires_confirmation",
		"optBoolean(\"truncated\"",
		"optInt(\"limit\"",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt",
		"Choose an installed chroot target",
		"FilterChip(selected = pane.category == category",
		"entry.state == \"blocked\"",
		"inventory is truncated by the bridge limit",
		"pane.preview.approvesOperation(\"catalog.apply\")",
	); err != nil {
		return err
	}
	if err := mustContain("resources/tools/sync-uid.yaml",
		"name: sync-uid",
		"script: sync-uid.sh",
	); err != nil {
		return err
	}
	if err := mustContain("resources/tool-scripts/sync-uid.sh",
		"host-managed by chrootctl",
		"exit 64",
	); err != nil {
		return err
	}
	if err := mustNotContain("resources/addon-scripts/install-winehq-staging.sh",
		"apt-get install -y wine ",
		"fallback",
	); err != nil {
		return err
	}
	for _, rel := range []string{
		"resources/addon-scripts/install-bleachbit.sh",
		"resources/addon-scripts/install-cinnamon.sh",
		"resources/addon-scripts/install-file-roller.sh",
		"resources/addon-scripts/install-gimp.sh",
		"resources/addon-scripts/install-gnome.sh",
		"resources/addon-scripts/install-librewolf.sh",
		"resources/addon-scripts/install-nautilus.sh",
		"resources/addon-scripts/install-nemo.sh",
		"resources/addon-scripts/install-sevenzip-wine.sh",
		"resources/addon-scripts/install-vlc.sh",
		"resources/addon-scripts/install-xfce4.sh",
		"resources/tool-scripts/setup-audio.sh",
		"resources/tool-scripts/setup-clipboard.sh",
		"resources/tool-scripts/setup-dev-basics.sh",
		"resources/tool-scripts/setup-flatpak.sh",
		"resources/tool-scripts/setup-github-ssh.sh",
		"resources/tool-scripts/setup-locales.sh",
		"resources/tool-scripts/setup-printer.sh",
		"resources/tool-scripts/setup-rdp-server.sh",
		"resources/tool-scripts/setup-shared-folders.sh",
		"resources/tool-scripts/setup-ssh-server.sh",
		"resources/tool-scripts/setup-sudo-user.sh",
		"resources/tool-scripts/setup-vnc-server.sh",
	} {
		if err := mustNotContain(rel, "pacman -Syu", "pacman -Suy", "pacman -syu", "pacman -suy"); err != nil {
			return err
		}
	}
	if err := mustContain("docs/audit/CHR13_CATALOG_PACKAGE_WORKFLOW.md",
		"`sync-uid` is blocked",
		"External catalog trust",
		"Package inventory",
	); err != nil {
		return err
	}
	return nil
}
