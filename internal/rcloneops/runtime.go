package rcloneops

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"

	chmodule "chrootctl/internal/module"
)

const (
	DefaultStateRoot  = "/data/adb/chrootctl"
	DefaultConfigPath = DefaultStateRoot + "/rclone/rclone.conf"
	RuntimeABI        = "arm64-v8a"
)

type Runtime struct {
	Executable string
	Config     string
}

type RuntimeInfo struct {
	Version           string   `json:"version"`
	Executable        string   `json:"executable"`
	Config            string   `json:"config"`
	ConfiguredRemotes []string `json:"configured_remotes"`
}

func RuntimeFromEnvironment() (Runtime, error) { return RuntimeFromEnviron(os.Environ()) }

func RuntimeFromEnviron(environ []string) (Runtime, error) {
	lookup := func(key string) string {
		prefix := key + "="
		for i := len(environ) - 1; i >= 0; i-- {
			if strings.HasPrefix(environ[i], prefix) {
				return strings.TrimSpace(strings.TrimPrefix(environ[i], prefix))
			}
		}
		return ""
	}
	type runtimeCandidate struct {
		path        string
		requireSeal bool
	}
	candidates := []runtimeCandidate{}
	if p := lookup("CHROOTCTL_RCLONE_PATH"); p != "" {
		// Explicit override is still ownership/mode checked below, but is allowed
		// outside the module seal for development and recovery workflows.
		candidates = append(candidates, runtimeCandidate{path: p})
	}
	mod := lookup("CHROOTCTL_MODULE_DIR")
	if mod != "" {
		candidates = append(candidates, runtimeCandidate{path: filepath.Join(mod, "runtime", RuntimeABI, "rclone"), requireSeal: true})
	}
	candidates = append(candidates,
		runtimeCandidate{path: "/data/adb/modules/chrootctl-magisk/runtime/" + RuntimeABI + "/rclone", requireSeal: true},
		runtimeCandidate{path: "/data/adb/modules_update/chrootctl-magisk/runtime/" + RuntimeABI + "/rclone", requireSeal: true},
	)
	// A root process must not silently execute an arbitrary PATH-provided binary.
	// Module/explicit paths form the privileged trust boundary; PATH fallback is
	// available to unprivileged CLI sessions or by explicit opt-in only.
	if os.Geteuid() != 0 || lookup("CHROOTCTL_RCLONE_ALLOW_PATH") == "1" {
		if p, err := exec.LookPath("rclone"); err == nil {
			candidates = append(candidates, runtimeCandidate{path: p})
		}
	}
	var executable string
	for _, candidate := range candidates {
		if candidate.path == "" {
			continue
		}
		abs, err := filepath.Abs(candidate.path)
		if err != nil {
			continue
		}
		st, err := os.Lstat(abs)
		if err != nil || !trustedRuntimeFile(st, os.Geteuid() == 0) {
			continue
		}
		if candidate.requireSeal {
			// Module-bundled rclone is accepted only when it belongs to the same
			// sealed runtime inventory as chrootctl. This prevents a stray root-owned
			// executable in the expected directory from becoming privileged transport.
			if err := chmodule.ValidateRuntime(filepath.Dir(abs)); err != nil {
				continue
			}
		}
		executable = abs
		break
	}
	if executable == "" {
		return Runtime{}, fmt.Errorf("rclone runtime is unavailable; bundle rclone in the module runtime or set CHROOTCTL_RCLONE_PATH")
	}
	config := lookup("CHROOTCTL_RCLONE_CONFIG")
	if config == "" {
		if st, err := os.Stat(DefaultConfigPath); err == nil && st.Mode().IsRegular() {
			config = DefaultConfigPath
		}
	}
	if config != "" {
		abs, err := filepath.Abs(config)
		if err != nil {
			return Runtime{}, fmt.Errorf("resolve rclone config: %w", err)
		}
		config = abs
		privileged := os.Geteuid() == 0
		if st, statErr := os.Lstat(config); statErr != nil || !trustedConfigFile(st, privileged) || !trustedPrivateDirectory(filepath.Dir(config), privileged) {
			return Runtime{}, fmt.Errorf("rclone config is unavailable or unsafe: %s", config)
		}
	}
	return Runtime{Executable: executable, Config: config}, nil
}

func trustedRuntimeFile(st os.FileInfo, privileged bool) bool {
	if st == nil || !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm()&0o100 == 0 || st.Mode().Perm()&0o022 != 0 {
		return false
	}
	if privileged {
		if raw, ok := st.Sys().(*syscall.Stat_t); !ok || raw.Uid != 0 {
			return false
		}
	}
	return true
}

func trustedPrivateDirectory(path string, privileged bool) bool {
	st, err := os.Lstat(path)
	if err != nil || st.Mode()&os.ModeSymlink != 0 || !st.IsDir() || st.Mode().Perm()&0o022 != 0 {
		return false
	}
	if privileged {
		if raw, ok := st.Sys().(*syscall.Stat_t); !ok || raw.Uid != 0 {
			return false
		}
	}
	return true
}

func trustedConfigFile(st os.FileInfo, privileged bool) bool {
	if st == nil || !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 || st.Size() <= 0 || st.Mode().Perm()&0o077 != 0 {
		return false
	}
	if privileged {
		if raw, ok := st.Sys().(*syscall.Stat_t); !ok || raw.Uid != 0 {
			return false
		}
	}
	return true
}

func (r Runtime) Probe(ctx context.Context) (RuntimeInfo, error) {
	probeCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	args := append([]string{"version"}, r.baseArgs()...)
	out, err := exec.CommandContext(probeCtx, r.Executable, args...).CombinedOutput()
	if err != nil {
		return RuntimeInfo{}, commandError("rclone version", err)
	}
	first := strings.TrimSpace(strings.SplitN(string(out), "\n", 2)[0])
	if !strings.HasPrefix(first, "rclone v") {
		return RuntimeInfo{}, fmt.Errorf("unexpected rclone version output")
	}
	names := []string{}
	if r.Config != "" {
		configured, err := r.ConfiguredRemoteNames()
		if err == nil {
			for name := range configured {
				names = append(names, name)
			}
			sort.Strings(names)
		}
	}
	return RuntimeInfo{Version: strings.TrimPrefix(first, "rclone "), Executable: r.Executable, Config: r.Config, ConfiguredRemotes: names}, nil
}

func (r Runtime) ConfiguredRemoteNames() (map[string]bool, error) {
	if r.Config == "" {
		return nil, fmt.Errorf("chrootctl rclone config path is not configured")
	}
	privileged := os.Geteuid() == 0
	st, err := os.Lstat(r.Config)
	if err != nil || !trustedConfigFile(st, privileged) || !trustedPrivateDirectory(filepath.Dir(r.Config), privileged) {
		return nil, fmt.Errorf("rclone config is unavailable or unsafe")
	}
	data, err := os.ReadFile(r.Config)
	if err != nil {
		return nil, fmt.Errorf("read rclone config: %w", err)
	}
	return remoteNamesInConfig(string(data)), nil
}

func remoteNamesInConfig(text string) map[string]bool {
	result := map[string]bool{}
	for _, raw := range strings.Split(text, "\n") {
		line := strings.TrimSpace(raw)
		if len(line) < 3 || !strings.HasPrefix(line, "[") || !strings.Contains(line, "]") {
			continue
		}
		name := strings.TrimSpace(line[1:strings.Index(line, "]")])
		if safeRemoteName.MatchString(name) {
			result[name] = true
		}
	}
	return result
}

// ValidateLocation verifies that every rclone:// location references a remote
// present in the active private configuration without contacting the provider.
func (r Runtime) ValidateLocation(values ...string) error {
	return r.requireConfigForRemote(values...)
}

func (r Runtime) requireConfigForRemote(values ...string) error {
	used := map[string]bool{}
	for _, value := range values {
		if parsed, err := parseLocation(value); err == nil {
			used[parsed.remote] = true
		}
	}
	if len(used) == 0 {
		return nil
	}
	configured, err := r.ConfiguredRemoteNames()
	if err != nil {
		return err
	}
	for remote := range used {
		if !configured[remote] {
			return fmt.Errorf("rclone remote %q is not configured", remote)
		}
	}
	return nil
}

func (r Runtime) baseArgs() []string {
	if r.Config == "" {
		return nil
	}
	return []string{"--config", r.Config}
}

func commandError(action string, err error) error {
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return fmt.Errorf("%s exited with status %d", action, exit.ExitCode())
	}
	return fmt.Errorf("%s: %w", action, err)
}

var secretDiagnosticPattern = regexp.MustCompile(`(?i)("?(?:token|password|client_secret|access_token|refresh_token|client_id|secret_access_key|access_key_id)"?\s*(?:=|:)\s*)("[^"]*"|'[^']*'|[^&\s,}]+)`)

func (r Runtime) sanitizeDiagnostic(value string) string {
	text := strings.TrimSpace(value)
	if r.Config != "" {
		text = strings.ReplaceAll(text, r.Config, "<rclone-config>")
	}
	return secretDiagnosticPattern.ReplaceAllString(text, "$1<redacted>")
}
