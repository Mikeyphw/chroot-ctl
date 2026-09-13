package repoctl

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type roomSchema struct {
	Database struct {
		Version      int    `json:"version"`
		IdentityHash string `json:"identityHash"`
		Entities     []struct {
			TableName string `json:"tableName"`
			Fields    []struct {
				ColumnName   string  `json:"columnName"`
				Affinity     string  `json:"affinity"`
				NotNull      bool    `json:"notNull"`
				DefaultValue *string `json:"defaultValue"`
			} `json:"fields"`
			PrimaryKey struct {
				AutoGenerate bool     `json:"autoGenerate"`
				ColumnNames  []string `json:"columnNames"`
			} `json:"primaryKey"`
			Indices []struct {
				Name        string   `json:"name"`
				Unique      bool     `json:"unique"`
				ColumnNames []string `json:"columnNames"`
			} `json:"indices"`
			ForeignKeys []json.RawMessage `json:"foreignKeys"`
		} `json:"entities"`
		SetupQueries []string `json:"setupQueries"`
	} `json:"database"`
}

func schemaHash(parts []string) string {
	var b strings.Builder
	for _, part := range parts {
		b.WriteString(part)
		b.WriteString("?:?")
	}
	sum := md5.Sum([]byte(b.String())) // Room's schema identity algorithm is MD5 by contract.
	return hex.EncodeToString(sum[:])
}

func roomIdentity(schema roomSchema) (string, error) {
	ids := make([]string, 0, len(schema.Database.Entities))
	for _, entity := range schema.Database.Entities {
		if len(entity.ForeignKeys) != 0 {
			return "", fmt.Errorf("CHR03 room identity helper does not support foreign keys in %s", entity.TableName)
		}
		pk := fmt.Sprintf("%t-[%s]", entity.PrimaryKey.AutoGenerate, strings.Join(entity.PrimaryKey.ColumnNames, ", "))
		fields := make([]string, 0, len(entity.Fields))
		for _, field := range entity.Fields {
			id := fmt.Sprintf("%s-%s-%t", field.ColumnName, field.Affinity, field.NotNull)
			if field.DefaultValue != nil {
				id += "-defaultValue=" + *field.DefaultValue
			}
			fields = append(fields, id)
		}
		indices := make([]string, 0, len(entity.Indices))
		for _, index := range entity.Indices {
			indices = append(indices, fmt.Sprintf("%t-%s-%s", index.Unique, index.Name, strings.Join(index.ColumnNames, ",")))
		}
		sort.Slice(fields, func(i, j int) bool { return strings.ToLower(fields[i]) < strings.ToLower(fields[j]) })
		sort.Slice(indices, func(i, j int) bool { return strings.ToLower(indices[i]) < strings.ToLower(indices[j]) })
		parts := append([]string{entity.TableName, pk}, fields...)
		parts = append(parts, indices...)
		ids = append(ids, schemaHash(parts))
	}
	sort.Slice(ids, func(i, j int) bool { return strings.ToLower(ids[i]) < strings.ToLower(ids[j]) })
	return schemaHash(ids), nil
}

// ValidateConfigRegistryFoundation is the executable CHR03 seal. Runtime tests
// exercise the behavior; this release invariant also prevents the config,
// registry and Room migration declarations from drifting apart later.
func ValidateConfigRegistryFoundation(root string) error {
	read := func(rel string) (string, error) {
		raw, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", err
		}
		return string(raw), nil
	}
	cfg, err := read("internal/config/config.go")
	if err != nil {
		return fmt.Errorf("CHR03 read config: %w", err)
	}
	for _, token := range []string{"chrootOverrideKeys", "validatePayloadKeys", "normalizeHostPath", "replaceFileAtomically", "inspect stable registry"} {
		if !strings.Contains(cfg, token) {
			return fmt.Errorf("CHR03 config invariant missing %q", token)
		}
	}
	reg, err := read("internal/registry/registry.go")
	if err != nil {
		return fmt.Errorf("CHR03 read registry: %w", err)
	}
	for _, token := range []string{"registry database path must be absolute", "idx_chroots_path_unique", "canonicalChrootPath", `from == "chroot_name"`, `to == "name"`, "RowsAffected", "NEW.name"} {
		if !strings.Contains(reg, token) {
			return fmt.Errorf("CHR03 registry invariant missing %q", token)
		}
	}
	container, err := read("internal/services/container.go")
	if err != nil {
		return fmt.Errorf("CHR03 read services container: %w", err)
	}
	for _, token := range []string{"type ResolvedTarget struct", "ResolveTarget", "record.Path", "cfg.ChrootRoot = filepath.Dir(root)"} {
		if !strings.Contains(container, token) {
			return fmt.Errorf("CHR03 target identity invariant missing %q", token)
		}
	}
	roomRaw, err := os.ReadFile(filepath.Join(root, "android", "app", "schemas", "com.mikeyphw.chrootctl.data.ChrootCtlDatabase", "4.json"))
	if err != nil {
		return fmt.Errorf("CHR03 read Room v4 schema: %w", err)
	}
	var schema roomSchema
	if err := json.Unmarshal(roomRaw, &schema); err != nil {
		return fmt.Errorf("CHR03 parse Room v4 schema: %w", err)
	}
	if schema.Database.Version != 4 {
		return fmt.Errorf("CHR03 Room schema version=%d want 4", schema.Database.Version)
	}
	for _, entity := range schema.Database.Entities {
		if entity.TableName != "chroots" {
			continue
		}
		for _, index := range entity.Indices {
			if index.Name == "index_chroots_name" {
				return fmt.Errorf("CHR03 redundant Room primary-key index still present")
			}
		}
	}
	identity, err := roomIdentity(schema)
	if err != nil {
		return err
	}
	if identity != schema.Database.IdentityHash {
		return fmt.Errorf("CHR03 Room identityHash=%s recomputed=%s", schema.Database.IdentityHash, identity)
	}
	migration, err := read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/DatabaseMigrations.kt")
	if err != nil {
		return fmt.Errorf("CHR03 read Room migrations: %w", err)
	}
	if !strings.Contains(migration, "MIGRATION_3_4") || !strings.Contains(migration, "DROP INDEX IF EXISTS index_chroots_name") {
		return fmt.Errorf("CHR03 Room 3->4 migration is incomplete")
	}
	return nil
}
