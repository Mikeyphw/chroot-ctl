package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateMountServiceRuntime is the executable CHR08 source seal. Behavioral
// tests live with system/controller/services/CLI; this check prevents the
// mount/session/service runtime from drifting back to fail-open evidence or
// optimistic lifecycle semantics.
func ValidateMountServiceRuntime(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR08 read %s: %w", rel, err)
		}
		return string(b), nil
	}
	require := func(rel string, tokens ...string) error {
		body, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if !strings.Contains(body, token) {
				return fmt.Errorf("CHR08 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	forbid := func(rel string, tokens ...string) error {
		body, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if strings.Contains(body, token) {
				return fmt.Errorf("CHR08 %s retains forbidden invariant %q", rel, token)
			}
		}
		return nil
	}

	if err := require("internal/system/system.go", "type MountRecord struct", "decodeProcMountField", "ParseMountTableDetailed", "MountTableDetailed", `\040`, `\011`, `\012`, `\134`); err != nil {
		return err
	}
	if err := require("internal/controller/controller.go", "mountSpecsValidated", "mountMatches", "rollbackMounts", "withDataDevSuid", "StatusChecked", "DoctorChecked", "LoginInvocation", "termux-x11 executable unavailable"); err != nil {
		return err
	}
	if err := require("internal/services/system.go", "StatusChecked", "DoctorChecked", "pathWritableWithoutMutation", "checkLogFile"); err != nil {
		return err
	}
	if err := forbid("internal/services/system.go", "func ensureWritable"); err != nil {
		return err
	}

	if err := require("internal/services/units.go", "serviceUnitNameRE", "parseBoolStrict", "splitQuotedFields", "trustedUnitPath", "EnabledByDefault", "serviceRuntimeState", "ChrootEnv: true", "TerminateProcessIdentity", "process tree survived", `"text": strings.Join(lines`, "network.target.service"); err != nil {
		return err
	}
	if err := forbid("internal/services/units.go", "st, _ := s.Status", "b, _ := os.ReadFile(p)", "b, _ := strconv.ParseBool", "return nil // external/system dependency"); err != nil {
		return err
	}

	cli, err := read("internal/cli/dispatch.go")
	if err != nil {
		return err
	}
	if !strings.Contains(cli, "serviceAddress") || !strings.Contains(cli, "LoginInvocation") {
		return fmt.Errorf("CHR08 CLI service/session normalization missing")
	}
	execInvocation := strings.Index(cli, "ExecInvocation(")
	prepare := strings.Index(cli[execInvocation:], "Controller.Prepare(")
	if execInvocation < 0 || prepare < 0 {
		return fmt.Errorf("CHR08 exec prevalidation ordering markers missing")
	}
	if !strings.Contains(cli, "a.ExitCode = 1") {
		return fmt.Errorf("CHR08 status/doctor failures must affect CLI exit status")
	}

	if err := require("internal/services/install.go", "foreign_arch_not_ready"); err != nil {
		return err
	}
	if err := require("internal/services/catalog.go", "CanExecuteForeignArch", "Controller.Prepare"); err != nil {
		return err
	}
	if err := require("internal/services/chroots.go", "StatusChecked", "mismatchedMountCount", "running_services", "service_attention"); err != nil {
		return err
	}
	if err := require("internal/clipboard/clipboard.go", "chrootctl-clipboard-wrapper:v1"); err != nil {
		return err
	}
	if err := require("resources/tool-scripts/setup-clipboard.sh", "chrootctl-clipboard-wrapper:v1"); err != nil {
		return err
	}

	if err := require("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt", "Release readiness", "releaseReadiness", "journalText", "optJSONArray(\"lines\")"); err != nil {
		return err
	}
	if err := require("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/OperationDao.kt", "markAllStale"); err != nil {
		return err
	}
	if err := require("android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt", "terminalConfirmed", "preserveForRecovery", "resumePersistedOperation"); err != nil {
		return err
	}
	if err := require("internal/services/release_readiness.go", "releaseEvidenceSchemaVersion = 4", "root_package", "installed_module", "native_runtime"); err != nil {
		return err
	}
	if err := forbid("internal/services/release_readiness.go", "android_localization_rtl"); err != nil {
		return err
	}
	return nil
}
