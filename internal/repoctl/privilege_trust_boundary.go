package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidatePrivilegeTrustBoundary is the executable CHR04 seal. It prevents
// wrapper, completion, privilege-provider and Android root-runtime policy from
// drifting back toward caller-controlled executable search paths.
func ValidatePrivilegeTrustBoundary(root string) error {
	read := func(rel string) (string, error) {
		raw, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", err
		}
		return string(raw), nil
	}
	wrapper, err := read("internal/cli/wrapper.go")
	if err != nil {
		return fmt.Errorf("CHR04 read wrapper: %w", err)
	}
	for _, forbidden := range []string{"command -v chrootctl", "exec su -c", "modules_update/chrootctl-magisk/system/bin/chrootctl", "_chc_path=${PATH", `sed "s/'/`} {
		if strings.Contains(wrapper, forbidden) {
			return fmt.Errorf("CHR04 wrapper retains unsafe token %q", forbidden)
		}
	}
	for _, required := range []string{"wrapperMarker", "transactionalInstall", "--force", "/system/bin/chrootctl"} {
		if !strings.Contains(wrapper, required) {
			return fmt.Errorf("CHR04 wrapper invariant missing %q", required)
		}
	}
	completion, err := read("internal/completion/query.go")
	if err != nil {
		return fmt.Errorf("CHR04 read completion query: %w", err)
	}
	for _, required := range []string{"LoadReadOnly", "OpenReadOnly", "strict read-only surface"} {
		if !strings.Contains(completion, required) {
			return fmt.Errorf("CHR04 completion invariant missing %q", required)
		}
	}
	sys, err := read("internal/system/system.go")
	if err != nil {
		return fmt.Errorf("CHR04 read system: %w", err)
	}
	for _, required := range []string{"ReexecWithRootIO", "trustedSudoPath", "trustedSuPath", "androidRootPath", "root re-exec failed"} {
		if !strings.Contains(sys, required) {
			return fmt.Errorf("CHR04 root re-exec invariant missing %q", required)
		}
	}
	resolver, err := read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt")
	if err != nil {
		return fmt.Errorf("CHR04 read runtime resolver: %w", err)
	}
	for _, forbidden := range []string{"CHROOTCTL_EXECUTABLE", "termuxHome", "termuxUsr"} {
		if strings.Contains(resolver, forbidden) {
			return fmt.Errorf("CHR04 Android runtime resolver retains %q", forbidden)
		}
	}
	for _, required := range []string{"isTrustedRootExecutable", "trustedRootExecutableMetadata", "Os.lstat"} {
		if !strings.Contains(resolver, required) {
			return fmt.Errorf("CHR04 Android runtime trust invariant missing %q", required)
		}
	}
	bridge, err := read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt")
	if err != nil {
		return fmt.Errorf("CHR04 read bridge process: %w", err)
	}
	if !strings.Contains(bridge, "environment().clear()") || !strings.Contains(bridge, "rootBridgeEnvironment()") {
		return fmt.Errorf("CHR04 bridge process does not sanitize root environment")
	}
	envStart := strings.Index(bridge, "internal fun rootBridgeEnvironment")
	envEnd := strings.Index(bridge, "internal class BridgeProcess")
	if envStart < 0 || envEnd <= envStart {
		return fmt.Errorf("CHR04 bridge environment function missing")
	}
	env := bridge[envStart:envEnd]
	for _, forbidden := range []string{"com.termux", ".local/bin"} {
		if strings.Contains(env, forbidden) {
			return fmt.Errorf("CHR04 root bridge environment retains %q", forbidden)
		}
	}

	raw, err := os.ReadFile(filepath.Join(root, "migration/contracts/v1/cli.json"))
	if err != nil {
		return err
	}
	// Decode through a map because contract metadata spans several fields and
	// assign distinct tags to all fields without obscuring the seal logic.
	var doc struct {
		CommandNodes []map[string]any `json:"commandNodes"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		return err
	}
	commands := map[string]map[string]any{}
	for _, item := range doc.CommandNodes {
		if name, _ := item["command"].(string); name != "" {
			commands[name] = item
		}
	}
	checks := map[string][2]string{"__complete": {"none", "read"}, "wrapper install": {"none", "mutate"}, "chroots rename": {"mutate-root", "mutate"}, "chroots diff": {"read-root", "read"}}
	for name, want := range checks {
		item := commands[name]
		if item == nil {
			return fmt.Errorf("CHR04 contract command missing %s", name)
		}
		if item["privilege"] != want[0] || item["mutability"] != want[1] {
			return fmt.Errorf("CHR04 contract metadata drift for %s", name)
		}
	}
	return nil
}
