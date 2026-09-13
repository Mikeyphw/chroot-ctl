package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateUserIdentitySafety keeps CHR12 from becoming a prose-only safety claim.
func ValidateUserIdentitySafety(root string) error {
	checks := map[string][]string{
		"internal/users/users.go": {
			"func (m *Manager) ensureMutableUser(",
			"rejectProtectedNewUser(",
			"sudoersRule(name)",
			"validateSudoersParentChain",
			"identityRowsErr",
			"Transactional: true",
			"rollback(){",
		},
		"internal/users/policy.go": {
			"protectedUsernames",
			"func classifyUser(",
			"func shellAllowsLogin(",
			"func sudoersBasename(name string) string",
			"NOPASSWD: ALL",
		},
		"internal/services/users.go": {
			"\"sudo\": u.Sudo",
			"\"protected\": u.Protected",
			"\"mutable\": u.Mutable",
		},
		"internal/bridge/backend.go": {
			"Protected or system users cannot be changed from the app.",
			"password_confirmation_mismatch",
			"policy_reasons",
		},
		"internal/bridge/specs_generated.go": {
			"Name: \"users.preview\"",
			"\"confirmPassword\"",
			"\"confirmation\"",
		},
		"migration/contracts/v1/bridge.json": {
			"\"name\": \"users.preview\"",
			"\"confirmPassword\"",
			"\"confirmation\"",
		},
		"android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt": {
			"val protectedAccount: Boolean",
			"val mutable: Boolean",
			"val policyReasons: List<String>",
		},
		"android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootWorkspacePolicy.kt": {
			"user.mutable && !userIsSystem(user)",
			"!user.mutable || user.protectedAccount || userIsSystem(user)",
		},
	}
	for rel, needles := range checks {
		data, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return fmt.Errorf("CHR12 read %s: %w", rel, err)
		}
		text := string(data)
		for _, needle := range needles {
			if !strings.Contains(text, needle) {
				return fmt.Errorf("CHR12 invariant missing %q in %s", needle, rel)
			}
		}
	}
	return nil
}
