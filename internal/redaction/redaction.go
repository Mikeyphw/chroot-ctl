package redaction

import (
	"fmt"
	"regexp"
	"strings"
)

var secretKeys = map[string]struct{}{
	"access_token": {}, "apikey": {}, "api_key": {}, "authorization": {}, "auth_token": {}, "cookie": {}, "csrf": {}, "client_secret": {}, "password": {},
	"confirmpassword": {}, "confirm_password": {}, "passphrase": {}, "private_key": {}, "secret": {}, "session": {}, "session_id": {}, "token": {},
}

var (
	bearerRE       = regexp.MustCompile(`(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/:=-]+`)
	assignmentRE   = regexp.MustCompile(`(?i)\b(password|passphrase|token|secret|authorization|access_token|api[_-]?key|client[_-]?secret|cookie|csrf|session[_-]?id)(\s*[:=]\s*)([^\s,;]+)`)
	opensslPassRE  = regexp.MustCompile(`(?i)(-pass\s+pass:)([^\s,;]+)`)
	urlCredsRE     = regexp.MustCompile(`(?i)\b([a-z][a-z0-9+.-]*://)([^\s/@:]+):([^\s/@]+)@`)
	awsAccessKeyRE = regexp.MustCompile(`\b(AKIA|ASIA)[A-Z0-9]{16}\b`)
	githubTokenRE  = regexp.MustCompile(`\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b`)
	privateKeyRE   = regexp.MustCompile(`(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----`)
	authHeaderRE   = regexp.MustCompile(`(?i)\b(authorization|x-api-key|cookie)(\s*:\s*)([^\r\n]+)`)
)

func isSecretKey(key string) bool {
	normalized := strings.ToLower(strings.ReplaceAll(strings.ReplaceAll(strings.TrimSpace(key), "-", "_"), ".", "_"))
	if _, ok := secretKeys[normalized]; ok {
		return true
	}
	return strings.HasSuffix(normalized, "_password") || strings.HasSuffix(normalized, "password") || strings.HasSuffix(normalized, "_token") || strings.HasSuffix(normalized, "token") || strings.HasSuffix(normalized, "_secret") || strings.Contains(normalized, "credential")
}

func String(value string) string {
	value = privateKeyRE.ReplaceAllString(value, "-----BEGIN PRIVATE KEY-----\n<redacted>\n-----END PRIVATE KEY-----")
	value = urlCredsRE.ReplaceAllString(value, "$1<redacted>:<redacted>@")
	value = authHeaderRE.ReplaceAllString(value, "$1$2<redacted>")
	value = bearerRE.ReplaceAllString(value, "$1 <redacted>")
	value = assignmentRE.ReplaceAllString(value, "$1$2<redacted>")
	value = opensslPassRE.ReplaceAllString(value, "$1<redacted>")
	value = awsAccessKeyRE.ReplaceAllString(value, "<redacted-aws-access-key>")
	return githubTokenRE.ReplaceAllString(value, "<redacted-github-token>")
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
	case map[string]string:
		out := make(map[string]string, len(item))
		for key, v := range item {
			if isSecretKey(key) {
				out[key] = "<redacted>"
			} else {
				out[key] = String(v)
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
