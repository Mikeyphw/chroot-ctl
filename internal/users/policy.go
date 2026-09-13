package users

import (
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
)

const systemUIDThreshold = 1000

var protectedUsernames = map[string]struct{}{
	"root": {}, "bin": {}, "daemon": {}, "sys": {}, "sync": {}, "games": {}, "man": {}, "lp": {}, "mail": {}, "news": {}, "uucp": {}, "proxy": {}, "www-data": {}, "backup": {}, "list": {}, "irc": {}, "gnats": {}, "nobody": {},
	"_apt": {}, "messagebus": {}, "polkitd": {}, "sshd": {}, "systemd-network": {}, "systemd-timesync": {}, "tcpdump": {}, "uuidd": {},
}

var nonLoginShells = map[string]struct{}{
	"": {}, "nologin": {}, "false": {}, "/usr/sbin/nologin": {}, "/sbin/nologin": {}, "/bin/false": {},
}

type SafetyPolicy struct {
	Protected bool
	System    bool
	Login     bool
	Mutable   bool
	Reasons   []string
}

func normalizeAccountName(name string) string { return strings.ToLower(strings.TrimSpace(name)) }

func isProtectedUsername(name string) bool {
	_, ok := protectedUsernames[normalizeAccountName(name)]
	return ok
}

func shellAllowsLogin(shell string) bool {
	v := strings.ToLower(strings.TrimSpace(shell))
	if _, blocked := nonLoginShells[v]; blocked {
		return false
	}
	return !strings.HasSuffix(v, "/nologin") && !strings.HasSuffix(v, "/false")
}

func classifyUser(u User) SafetyPolicy {
	name := normalizeAccountName(u.Username)
	reasons := []string{}
	protected := isProtectedUsername(name)
	if protected {
		reasons = append(reasons, "protected account")
	}
	uid, uidErr := strconv.Atoi(strings.TrimSpace(u.UID))
	system := protected
	if uidErr == nil && uid >= 0 && uid < systemUIDThreshold {
		system = true
		if name != "root" {
			reasons = append(reasons, fmt.Sprintf("uid below %d", systemUIDThreshold))
		}
	}
	login := shellAllowsLogin(u.Shell)
	if !login {
		system = true
		reasons = append(reasons, "non-login shell")
	}
	mutable := !protected && !system
	return SafetyPolicy{Protected: protected, System: system, Login: login, Mutable: mutable, Reasons: compactReasons(reasons)}
}

func compactReasons(in []string) []string {
	seen := map[string]struct{}{}
	out := []string{}
	for _, v := range in {
		if v == "" {
			continue
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	return out
}

func sudoersBasename(name string) string       { return name }
func legacySudoersBasename(name string) string { return "90-chrootctl-" + name }

func sudoersRule(name string) string { return name + " ALL=(ALL:ALL) NOPASSWD: ALL\n" }

func sudoersRuleMentionsUser(data, name string) bool {
	for _, line := range strings.Split(data, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) > 0 && fields[0] == name {
			return true
		}
	}
	return false
}

func safeChildPath(base, rel string) (string, error) {
	clean := filepath.Clean(rel)
	if filepath.IsAbs(clean) || strings.HasPrefix(clean, ".."+string(filepath.Separator)) || clean == ".." {
		return "", fmt.Errorf("unsafe relative path: %s", rel)
	}
	return filepath.Join(base, clean), nil
}
