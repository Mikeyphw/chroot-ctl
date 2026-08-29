package redaction

import (
	"fmt"
	"regexp"
	"strings"
)

var secretKeys = map[string]struct{}{
	"access_token": {}, "authorization": {}, "cookie": {}, "csrf": {}, "password": {},
	"confirmpassword": {}, "confirm_password": {}, "passphrase": {}, "secret": {}, "token": {},
}
var bearerRE = regexp.MustCompile(`(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/-]+=*`)
var assignmentRE = regexp.MustCompile(`(?i)\b(password|passphrase|token|secret|authorization|access_token|cookie|csrf)(\s*[:=]\s*)([^\s,;]+)`)
var opensslPassRE = regexp.MustCompile(`(?i)(-pass\s+pass:)([^\s,;]+)`)

func isSecretKey(key string) bool {
	normalized := strings.ToLower(strings.ReplaceAll(strings.TrimSpace(key), "-", "_"))
	if _, ok := secretKeys[normalized]; ok {
		return true
	}
	return strings.HasSuffix(normalized, "_password") || strings.HasSuffix(normalized, "password") || strings.HasSuffix(normalized, "_token") || strings.HasSuffix(normalized, "token")
}

func String(value string) string {
	value = bearerRE.ReplaceAllString(value, "$1 <redacted>")
	value = assignmentRE.ReplaceAllString(value, "$1$2<redacted>")
	return opensslPassRE.ReplaceAllString(value, "$1<redacted>")
}

func Value(value any) any {
	switch item := value.(type) {
	case map[string]any:
		out := make(map[string]any, len(item))
		for key, v := range item {
			if isSecretKey(key) {
				out[key] = "<redacted>"
			} else {
				out[key] = Value(v)
			}
		}
		return out
	case []any:
		out := make([]any, len(item))
		for i, v := range item {
			out[i] = Value(v)
		}
		return out
	case []string:
		out := make([]string, len(item))
		for i, v := range item {
			out[i] = String(v)
		}
		return out
	case string:
		return String(item)
	case fmt.Stringer:
		return String(item.String())
	default:
		return value
	}
}
