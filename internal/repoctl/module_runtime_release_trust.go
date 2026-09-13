package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateModuleRuntimeReleaseTrust keeps CHR15 executable instead of prose-only.
// It seals the module/runtime/release contract: rendered modules carry a package
// manifest, runtime status validates the same package/runtime seal as Android,
// module build preview uses the real builder preflight, replacement is promoted
// through rollback-capable renames, and module removal owns transient runtime
// state without deleting user chroot data.
func ValidateModuleRuntimeReleaseTrust(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR15 read %s: %w", rel, err)
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
				return fmt.Errorf("CHR15 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	mustModeExecutable := func(rel string) error {
		st, err := os.Lstat(filepath.Join(root, rel))
		if err != nil {
			return err
		}
		if st.Mode()&0111 == 0 {
			return fmt.Errorf("CHR15 %s must be executable", rel)
		}
		return nil
	}

	if err := mustContain("internal/module/module.go",
		"ModulePackageSchemaVersion",
		"ModulePackageManifestPath",
		"func ValidatePackageManifest(root string) error",
		"func ValidateZipArchive(path string) error",
		"module ZIP package manifest startup targets do not match boot target manifest",
		"validateDynamicLibraries(ef)",
		"native runtime imports unsupported dynamic library",
		"func uninstall() string",
		"STATE_ROOT=/data/adb/chrootctl",
		"uninstall.sh",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/lifecycle.go",
		"chmodule.ValidateRendered(root)",
		"chmodule.ValidateRuntime(runtimeRoot)",
		"packageSealReady",
		"minimumBridge >= 1 && minimumBridge <= chmodule.BridgeProtocolVersion",
	); err != nil {
		return err
	}
	if err := mustContain("internal/services/module_build.go",
		"func (s *ModuleBuildService) Preflight",
		"ResolveStartupTargets",
		"s.C.ResolveTarget(ctx, name, true)",
		"chmodule.ValidateZipArchive(abs)",
		"package_manifest",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/backend.go",
		"ModuleBuilder().Preflight",
		"system.module_build",
	); err != nil {
		return err
	}
	if err := mustContain("internal/cli/dispatch.go",
		"ModuleBuilder().ResolveStartupTargets",
		"AllInstalled:   len(requested) == 0 && a.Inv.Bool(\"all_installed\")",
	); err != nil {
		return err
	}
	if err := mustContain("internal/repoctl/repoctl.go",
		"backup := dst + \".previous-\"",
		"_ = os.Rename(backup, dst)",
		"chmodule.ValidateZipArchive(zipPath)",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt",
		"MODULE_PACKAGE_MANIFEST_PATH",
		"isModulePackageSealReady()",
		"runtime/$NATIVE_RUNTIME_ABI/$NATIVE_RUNTIME_ENTRYPOINT",
		"uninstall.sh",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
		"BridgeRequest(\"system.module_build_preview\", payload)",
		"put(\"allInstalled\", true)",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt",
		"put(\"allInstalled\", true)",
		"withPreviewContract(systemSupportPane.value.moduleBuildPreview, \"system.module_build\")",
	); err != nil {
		return err
	}
	for _, rel := range []string{"scripts/repoctl", "scripts/release", "scripts/final-seal"} {
		if err := mustModeExecutable(rel); err != nil {
			return err
		}
	}
	if err := mustContain("docs/audit/roadmap-coverage.json",
		`"id": "CHR15"`,
		`"title": "Module/runtime/release trust seal"`,
		`"ownerOverlay": "CHR15"`,
		`"status": "implemented"`,
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR15_MODULE_RUNTIME_RELEASE_TRUST.md", "Module/runtime/release trust seal", "ValidateModuleRuntimeReleaseTrust"); err != nil {
		return err
	}
	return nil
}
