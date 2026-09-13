package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateAndroidOperationRoomRecovery keeps CHR18 executable instead of prose-only.
// It seals the Android operation admission, Room reconciliation and recovery layer:
// foreground requests are not silently discarded, active Room ghosts reconcile against
// authoritative backend state, retry/snapshot actions are metadata gated, and recovery
// polling has bounded exit conditions.
func ValidateAndroidOperationRoomRecovery(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR18 read %s: %w", rel, err)
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
				return fmt.Errorf("CHR18 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/OperationEntities.kt",
		"parentOperationId",
		"requestJson",
		"retryJson",
		"retryable",
		"missingInBackend",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/DatabaseMigrations.kt",
		"MIGRATION_4_5",
		"ALTER TABLE operations ADD COLUMN retryable",
		"index_operations_missingInBackend",
	); err != nil {
		return err
	}

	roomRaw, err := os.ReadFile(filepath.Join(root, "android", "app", "schemas", "com.mikeyphw.chrootctl.data.ChrootCtlDatabase", "5.json"))
	if err != nil {
		return fmt.Errorf("CHR18 read Room v5 schema: %w", err)
	}
	var schema roomSchema
	if err := json.Unmarshal(roomRaw, &schema); err != nil {
		return fmt.Errorf("CHR18 parse Room v5 schema: %w", err)
	}
	if schema.Database.Version != 5 {
		return fmt.Errorf("CHR18 Room schema version=%d want 5", schema.Database.Version)
	}
	identity, err := roomIdentity(schema)
	if err != nil {
		return err
	}
	if identity != schema.Database.IdentityHash {
		return fmt.Errorf("CHR18 Room identityHash=%s recomputed=%s", schema.Database.IdentityHash, identity)
	}
	foundRoomMetadata := map[string]bool{}
	for _, entity := range schema.Database.Entities {
		if entity.TableName != "operations" {
			continue
		}
		for _, field := range entity.Fields {
			if field.ColumnName == "recoveryActionsJson" || field.ColumnName == "missingInBackend" {
				foundRoomMetadata[field.ColumnName] = true
			}
		}
	}
	if !foundRoomMetadata["recoveryActionsJson"] || !foundRoomMetadata["missingInBackend"] {
		return fmt.Errorf("CHR18 Room v5 schema missing operation recovery metadata fields")
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/OperationDao.kt",
		"replaceAuthoritativeSnapshot",
		"markActiveMissingFromBackend",
		"MISSING_BACKEND_OPERATION",
		"prune: Boolean = true",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
		"OperationRecoveryContract",
		"operations.find_request",
		"fallbackKind = operation",
		"recordOperationEvent",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/OperationRecoveryContract.kt",
		"previewBoundOperations",
		"retry_with_fixes",
		"containsRedacted",
		"bridge_stream_interrupted",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt",
		"rejectSecondOperation",
		"MAX_RECONCILE_ATTEMPTS",
		"MAX_SERVICE_RECOVERY_ATTEMPTS",
		"onTimeout",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ActivityRecoveryPolicy.kt",
		"retryable && recoveryActions.contains",
		"!missingInBackend",
		"state.lowercase() != \"cancelling\"",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/backend.go",
		"operations.find_request",
		"FindByRequestID",
		"MISSING_REQUEST_ID",
	); err != nil {
		return err
	}
	if err := mustContain("internal/operations/manager.go", "FindByRequestID", "ListAll(nil)"); err != nil {
		return err
	}
	if err := mustContain("docs/audit/roadmap-coverage.json",
		`"id": "CHR18"`,
		`"title": "Android operation/Room/recovery engine"`,
		`"ownerOverlay": "CHR18"`,
		`"status": "implemented"`,
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR18_ANDROID_OPERATION_ROOM_RECOVERY.md", "Android operation/Room/recovery engine", "ValidateAndroidOperationRoomRecovery"); err != nil {
		return err
	}
	return nil
}
