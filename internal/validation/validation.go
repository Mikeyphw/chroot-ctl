package validation

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var (
	safeNameRE     = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)
	safeSnapshotRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$`)
	safeCatalogRE  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$`)
	serviceNameRE  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9@._:-]{0,127}$`)
	usernameRE     = regexp.MustCompile(`^[a-z_][a-z0-9_-]{0,31}[$]?$`)
)

func stringRepr(value string) string {
	value = strings.ReplaceAll(value, `\`, `\\`)
	value = strings.ReplaceAll(value, `'`, `\'`)
	value = strings.ReplaceAll(value, "\n", `\n`)
	value = strings.ReplaceAll(value, "\r", `\r`)
	value = strings.ReplaceAll(value, "\t", `\t`)
	return "'" + value + "'"
}

func cleanText(value any, field string) (string, error) {
	text, ok := value.(string)
	if !ok {
		return "", fmt.Errorf("%s must be a string", field)
	}
	text = strings.TrimSpace(text)
	if text == "" {
		return "", fmt.Errorf("%s is required", field)
	}
	if strings.ContainsAny(text, "\x00\n\r") {
		return "", fmt.Errorf("%s must be a single-line value", field)
	}
	return text, nil
}

func validateBasename(value any, field string, pattern *regexp.Regexp) (string, error) {
	text, err := cleanText(value, field)
	if err != nil {
		return "", err
	}
	if text == "." || text == ".." || strings.Contains(text, "/") || strings.Contains(text, `\`) {
		return "", fmt.Errorf("%s must be a safe basename", field)
	}
	if !pattern.MatchString(text) {
		return "", fmt.Errorf("invalid %s: %s", field, stringRepr(text))
	}
	return text, nil
}

func ChrootName(value any) (string, error) {
	return ChrootNameField(value, "chroot name")
}

func ChrootNameField(value any, field string) (string, error) {
	return validateBasename(value, field, safeNameRE)
}

func SnapshotName(value any) (string, error) {
	return SnapshotNameField(value, "snapshot name")
}

func SnapshotNameField(value any, field string) (string, error) {
	return validateBasename(value, field, safeSnapshotRE)
}

func CatalogName(value any) (string, error) {
	return CatalogNameField(value, "catalog name")
}

func CatalogNameField(value any, field string) (string, error) {
	return validateBasename(value, field, safeCatalogRE)
}

func ServiceName(value any) (string, error) {
	return ServiceNameField(value, "service name")
}

func ServiceNameField(value any, field string) (string, error) {
	return validateBasename(value, field, serviceNameRE)
}

func Username(value any) (string, error) {
	return UsernameField(value, "username")
}

func UsernameField(value any, field string) (string, error) {
	text, err := cleanText(value, field)
	if err != nil {
		return "", err
	}
	if !usernameRE.MatchString(text) {
		return "", fmt.Errorf("invalid %s: %s", field, stringRepr(text))
	}
	return text, nil
}

func StrictBool(value any, field string) (bool, error) {
	result, ok := value.(bool)
	if !ok {
		return false, fmt.Errorf("%s must be a JSON boolean", field)
	}
	return result, nil
}

func OptionalBool(mapping map[string]any, keys []string, defaultValue bool, field string) (bool, error) {
	for _, key := range keys {
		value, ok := mapping[key]
		if !ok || value == nil {
			continue
		}
		name := field
		if name == "" {
			name = key
		}
		return StrictBool(value, name)
	}
	return defaultValue, nil
}

func integerValue(value any) (int64, bool) {
	switch typed := value.(type) {
	case int:
		return int64(typed), true
	case int8:
		return int64(typed), true
	case int16:
		return int64(typed), true
	case int32:
		return int64(typed), true
	case int64:
		return typed, true
	case uint:
		if uint64(typed) > uint64(^uint64(0)>>1) {
			return 0, false
		}
		return int64(typed), true
	case uint8:
		return int64(typed), true
	case uint16:
		return int64(typed), true
	case uint32:
		return int64(typed), true
	case uint64:
		if typed > uint64(^uint64(0)>>1) {
			return 0, false
		}
		return int64(typed), true
	case json.Number:
		parsed, err := strconv.ParseInt(string(typed), 10, 64)
		return parsed, err == nil
	default:
		return 0, false
	}
}

func BoundedInt(value any, field string, minimum, maximum int64) (int64, error) {
	parsed, ok := integerValue(value)
	if !ok {
		return 0, fmt.Errorf("%s must be an integer", field)
	}
	if parsed < minimum || parsed > maximum {
		return 0, fmt.Errorf("%s must be between %d and %d", field, minimum, maximum)
	}
	return parsed, nil
}

func OptionalBoundedInt(mapping map[string]any, key string, defaultValue, minimum, maximum int64) (int64, error) {
	value, ok := mapping[key]
	if !ok || value == nil {
		return defaultValue, nil
	}
	return BoundedInt(value, key, minimum, maximum)
}

func StrictStringList(value any, field string, allowEmpty bool) ([]string, error) {
	if value == nil {
		return []string{}, nil
	}
	items, ok := value.([]any)
	if !ok {
		if stringsValue, ok := value.([]string); ok {
			items = make([]any, len(stringsValue))
			for index := range stringsValue {
				items[index] = stringsValue[index]
			}
		} else {
			return nil, fmt.Errorf("%s must be a JSON array of strings", field)
		}
	}
	result := make([]string, 0, len(items))
	for index, item := range items {
		text, ok := item.(string)
		if !ok {
			return nil, fmt.Errorf("%s[%d] must be a string", field, index)
		}
		text = strings.TrimSpace(text)
		if text == "" && !allowEmpty {
			return nil, fmt.Errorf("%s[%d] must not be empty", field, index)
		}
		if text != "" {
			result = append(result, text)
		}
	}
	return result, nil
}

func UniqueCatalogNames(value any, field string) ([]string, error) {
	if field == "" {
		field = "names"
	}
	names, err := StrictStringList(value, field, false)
	if err != nil {
		return nil, err
	}
	seen := make(map[string]struct{}, len(names))
	result := make([]string, 0, len(names))
	for _, name := range names {
		safe, err := CatalogNameField(name, field+" item")
		if err != nil {
			return nil, err
		}
		if _, exists := seen[safe]; exists {
			return nil, fmt.Errorf("duplicate %s item: %s", field, safe)
		}
		seen[safe] = struct{}{}
		result = append(result, safe)
	}
	return result, nil
}

func RelativeChrootPath(value any) (string, error) {
	return RelativeChrootPathField(value, "path")
}

func RelativeChrootPathField(value any, field string) (string, error) {
	text, err := cleanText(value, field)
	if err != nil {
		return "", err
	}
	if strings.HasPrefix(text, "/") {
		return "", fmt.Errorf("%s must be relative to the chroot root", field)
	}
	// pathlib.PurePosixPath normalizes empty and "." components before Python's
	// validation loop. Preserve the original text while rejecting parent traversal.
	for _, part := range strings.Split(text, "/") {
		if part == ".." {
			return "", fmt.Errorf("%s must not contain empty, current, or parent path segments", field)
		}
	}
	return text, nil
}

func SafeArchiveName(value any) (string, error) {
	return SafeArchiveNameField(value, "archive")
}

func SafeArchiveNameField(value any, field string) (string, error) {
	return cleanText(value, field)
}
