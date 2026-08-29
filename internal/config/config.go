package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"chrootctl/internal/validation"
)

const (
	AndroidStateRoot  = "/data/adb/chrootctl"
	LegacyTermuxHome  = "/data/data/com.termux/files/home"
	DefaultChrootRoot = "/data/local/tmp"
	DefaultTermuxHome = "/data/data/com.termux/files/home"
	DefaultTermuxPref = "/data/data/com.termux/files/usr"
	DefaultLogFile    = "/sdcard/.logs/chrootctl.log"
)

var DefaultDNSServers = []string{"8.8.8.8", "1.1.1.1"}

var DefaultMediaMounts = []BindMount{
	{Source: "/sdcard/Documents", Target: "home/mike/Documents", Enabled: true},
	{Source: "/sdcard/Download", Target: "home/mike/Downloads", Enabled: true},
	{Source: "/sdcard/Pictures", Target: "home/mike/Pictures", Enabled: true},
	{Source: "/sdcard/Movies", Target: "home/mike/Videos", Enabled: true},
}

type BindMount struct {
	Source   string `json:"source"`
	Target   string `json:"target"`
	Enabled  bool   `json:"enabled"`
	ReadOnly bool   `json:"read_only"`
}

type ChrootConfig struct {
	ChrootRoot                string                    `json:"chroot_root"`
	DistroName                string                    `json:"distro_name"`
	Username                  string                    `json:"username"`
	TargetArch                string                    `json:"target_arch"`
	TermuxHome                string                    `json:"termux_home"`
	TermuxPrefix              string                    `json:"termux_prefix"`
	LogFile                   string                    `json:"log_file"`
	DatabasePath              string                    `json:"database_path"`
	ShellPath                 string                    `json:"shell_path"`
	MountDataWithDevSuid      bool                      `json:"mount_data_with_dev_suid"`
	DevShmSize                string                    `json:"dev_shm_size"`
	MediaMounts               []BindMount               `json:"media_mounts"`
	ExtraBindMounts           []BindMount               `json:"extra_bind_mounts"`
	ExtraPackages             []string                  `json:"extra_packages"`
	Locale                    string                    `json:"locale"`
	DNSServers                []string                  `json:"dns_servers"`
	PostInstallHooks          []string                  `json:"post_install_hooks"`
	InstallProfile            *string                   `json:"install_profile"`
	SnapshotDir               string                    `json:"snapshot_dir"`
	SnapshotBeforeDestructive bool                      `json:"snapshot_before_destructive"`
	ToolManifestDirs          []string                  `json:"tool_manifest_dirs"`
	ToolScriptDirs            []string                  `json:"tool_script_dirs"`
	AddonManifestDirs         []string                  `json:"addon_manifest_dirs"`
	AddonScriptDirs           []string                  `json:"addon_script_dirs"`
	ServiceDirs               []string                  `json:"service_dirs"`
	ServiceStateDir           string                    `json:"service_state_dir"`
	ServiceLogDir             string                    `json:"service_log_dir"`
	ChrootOverrides           map[string]map[string]any `json:"chroot_overrides"`
}

type RuntimeContext struct {
	Android         bool
	Home            string
	AndroidStateDir string
	LegacyHome      string
}

func DetectRuntime() RuntimeContext {
	home, _ := os.UserHomeDir()
	_, appProcessErr := os.Stat("/system/bin/app_process")
	return RuntimeContext{
		Android:         os.Getenv("ANDROID_ROOT") != "" || appProcessErr == nil,
		Home:            home,
		AndroidStateDir: AndroidStateRoot,
		LegacyHome:      LegacyTermuxHome,
	}
}

func normalizeRuntime(runtime RuntimeContext) RuntimeContext {
	if runtime.Home == "" {
		runtime.Home, _ = os.UserHomeDir()
	}
	if runtime.AndroidStateDir == "" {
		runtime.AndroidStateDir = AndroidStateRoot
	}
	if runtime.LegacyHome == "" {
		runtime.LegacyHome = LegacyTermuxHome
	}
	return runtime
}

func Default(runtime RuntimeContext) ChrootConfig {
	runtime = normalizeRuntime(runtime)
	stateRoot := defaultStateRoot(runtime)
	return ChrootConfig{
		ChrootRoot:                DefaultChrootRoot,
		DistroName:                "ubuntu",
		Username:                  "mike",
		TargetArch:                "arm64",
		TermuxHome:                DefaultTermuxHome,
		TermuxPrefix:              DefaultTermuxPref,
		LogFile:                   DefaultLogFile,
		DatabasePath:              filepath.Join(stateRoot, "chroots.sqlite3"),
		ShellPath:                 "/usr/bin/zsh",
		MountDataWithDevSuid:      true,
		DevShmSize:                "256M",
		MediaMounts:               cloneMounts(DefaultMediaMounts),
		ExtraBindMounts:           []BindMount{},
		ExtraPackages:             []string{},
		Locale:                    "en_US.UTF-8",
		DNSServers:                append([]string(nil), DefaultDNSServers...),
		PostInstallHooks:          []string{},
		InstallProfile:            nil,
		SnapshotDir:               filepath.Join(stateRoot, "snapshots"),
		SnapshotBeforeDestructive: false,
		ToolManifestDirs:          []string{},
		ToolScriptDirs:            []string{},
		AddonManifestDirs:         []string{},
		AddonScriptDirs:           []string{},
		ServiceDirs:               []string{filepath.Join(stateRoot, "services")},
		ServiceStateDir:           filepath.Join(stateRoot, "run", "services"),
		ServiceLogDir:             filepath.Join(stateRoot, "logs", "services"),
		ChrootOverrides:           map[string]map[string]any{},
	}
}

func defaultStateRoot(runtime RuntimeContext) string {
	if runtime.Android {
		return runtime.AndroidStateDir
	}
	return filepath.Join(runtime.Home, ".local", "share", "chrootctl")
}

func DefaultConfigPath(runtime RuntimeContext) string {
	runtime = normalizeRuntime(runtime)
	if runtime.Android {
		return filepath.Join(runtime.AndroidStateDir, "config.json")
	}
	return filepath.Join(runtime.Home, ".config", "chrootctl", "config.json")
}

func (cfg ChrootConfig) ChrootBase() string {
	return filepath.Join(cfg.ChrootRoot, cfg.DistroName)
}

func (cfg ChrootConfig) UserHomeInChroot() string {
	return filepath.Join(cfg.ChrootBase(), "home", cfg.Username)
}

func (cfg ChrootConfig) TermuxHomeInChroot() string {
	return filepath.Join(cfg.ChrootBase(), "home", "termux")
}

func (cfg ChrootConfig) ResolvedShell(availablePaths map[string]bool) string {
	if availablePaths[cfg.ShellPath] {
		return cfg.ShellPath
	}
	if availablePaths["/bin/bash"] {
		return "/bin/bash"
	}
	return cfg.ShellPath
}

func (cfg ChrootConfig) ForChroot(name string, runtime RuntimeContext) (ChrootConfig, error) {
	safe, err := validation.ChrootName(name)
	if err != nil {
		return ChrootConfig{}, err
	}
	result := cfg.Clone()
	result.DistroName = safe
	overrides := cfg.ChrootOverrides[safe]
	if len(overrides) == 0 {
		return result, nil
	}
	return ApplyPayload(result, overrides, runtime)
}

func (cfg ChrootConfig) Clone() ChrootConfig {
	cfg.MediaMounts = cloneMounts(cfg.MediaMounts)
	cfg.ExtraBindMounts = cloneMounts(cfg.ExtraBindMounts)
	cfg.ExtraPackages = cloneStrings(cfg.ExtraPackages)
	cfg.DNSServers = cloneStrings(cfg.DNSServers)
	cfg.PostInstallHooks = cloneStrings(cfg.PostInstallHooks)
	cfg.ToolManifestDirs = cloneStrings(cfg.ToolManifestDirs)
	cfg.ToolScriptDirs = cloneStrings(cfg.ToolScriptDirs)
	cfg.AddonManifestDirs = cloneStrings(cfg.AddonManifestDirs)
	cfg.AddonScriptDirs = cloneStrings(cfg.AddonScriptDirs)
	cfg.ServiceDirs = cloneStrings(cfg.ServiceDirs)
	cfg.ChrootOverrides = cloneOverrides(cfg.ChrootOverrides)
	if cfg.InstallProfile != nil {
		value := *cfg.InstallProfile
		cfg.InstallProfile = &value
	}
	return cfg
}

type ChrootCounter func(path string) (int, error)

type loadSettings struct {
	runtime RuntimeContext
	counter ChrootCounter
}

type LoadOption func(*loadSettings)

func WithRuntime(runtime RuntimeContext) LoadOption {
	return func(settings *loadSettings) { settings.runtime = runtime }
}

func WithChrootCounter(counter ChrootCounter) LoadOption {
	return func(settings *loadSettings) { settings.counter = counter }
}

func Load(path string, options ...LoadOption) (ChrootConfig, error) {
	settings := loadSettings{runtime: DetectRuntime()}
	for _, option := range options {
		option(&settings)
	}
	settings.runtime = normalizeRuntime(settings.runtime)
	if path == "" {
		if err := MigrateAndroidRuntimeLayout(settings.runtime, settings.counter); err != nil {
			return ChrootConfig{}, err
		}
		path = DefaultConfigPath(settings.runtime)
	}
	base := Default(settings.runtime)
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return base, nil
	}
	if err != nil {
		return ChrootConfig{}, err
	}
	payload, err := decodeObject(data)
	if err != nil {
		return ChrootConfig{}, err
	}
	cfg, err := ApplyPayload(base, payload, settings.runtime)
	if err != nil {
		return ChrootConfig{}, err
	}
	if raw, ok := payload["chroot_overrides"]; ok {
		overrides, err := normalizeOverrides(raw)
		if err != nil {
			return ChrootConfig{}, err
		}
		cfg.ChrootOverrides = overrides
	}
	return cfg, nil
}

func ApplyPayload(current ChrootConfig, payload map[string]any, runtime RuntimeContext) (ChrootConfig, error) {
	runtime = normalizeRuntime(runtime)
	cfg := current.Clone()
	repositories := map[string]any{}
	if raw, exists := payload["repositories"]; exists && raw != nil {
		mapping, ok := raw.(map[string]any)
		if !ok {
			return ChrootConfig{}, errors.New("repositories must be a mapping")
		}
		repositories = mapping
	}

	var err error
	if cfg.ChrootRoot, err = optionalString(payload, "chroot_root", cfg.ChrootRoot); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.DistroName, err = optionalString(payload, "distro_name", cfg.DistroName); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.Username, err = optionalString(payload, "username", cfg.Username); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.TargetArch, err = optionalString(payload, "target_arch", cfg.TargetArch); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.TermuxHome, err = optionalString(payload, "termux_home", cfg.TermuxHome); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.TermuxPrefix, err = optionalString(payload, "termux_prefix", cfg.TermuxPrefix); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.LogFile, err = optionalString(payload, "log_file", cfg.LogFile); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.DatabasePath, err = optionalString(payload, "database_path", cfg.DatabasePath); err != nil {
		return ChrootConfig{}, err
	}
	cfg.DatabasePath = normalizeAndroidRuntimePath(cfg.DatabasePath, runtime, legacyDatabasePath(runtime), filepath.Join(runtime.AndroidStateDir, "chroots.sqlite3"))
	if cfg.ShellPath, err = optionalString(payload, "shell_path", cfg.ShellPath); err != nil {
		return ChrootConfig{}, err
	}
	if value, ok := payload["mount_data_with_dev_suid"]; ok {
		cfg.MountDataWithDevSuid, err = validation.StrictBool(value, "mount_data_with_dev_suid")
		if err != nil {
			return ChrootConfig{}, err
		}
	}
	if cfg.DevShmSize, err = optionalString(payload, "dev_shm_size", cfg.DevShmSize); err != nil {
		return ChrootConfig{}, err
	}
	if value, ok := payload["media_mounts"]; ok {
		cfg.MediaMounts, err = normalizeMounts(value)
		if err != nil {
			return ChrootConfig{}, err
		}
	}
	if value, ok := payload["extra_bind_mounts"]; ok {
		cfg.ExtraBindMounts, err = normalizeMounts(value)
		if err != nil {
			return ChrootConfig{}, err
		}
	}
	if value, ok := payload["extra_packages"]; ok {
		cfg.ExtraPackages, err = normalizeStrings(value)
		if err != nil {
			return ChrootConfig{}, err
		}
	}
	if cfg.Locale, err = optionalString(payload, "locale", cfg.Locale); err != nil {
		return ChrootConfig{}, err
	}
	if value, ok := payload["dns_servers"]; ok {
		values, listErr := normalizeStrings(value)
		if listErr != nil {
			return ChrootConfig{}, listErr
		}
		if len(values) != 0 {
			cfg.DNSServers = values
		}
	}
	if value, ok := payload["post_install_hooks"]; ok {
		cfg.PostInstallHooks, err = normalizeStrings(value)
		if err != nil {
			return ChrootConfig{}, err
		}
	}
	if value, ok := payload["install_profile"]; ok {
		if value == nil {
			cfg.InstallProfile = nil
		} else {
			text, ok := value.(string)
			if !ok {
				return ChrootConfig{}, errors.New("install_profile must be a string or null")
			}
			cfg.InstallProfile = &text
		}
	}
	if cfg.SnapshotDir, err = optionalString(payload, "snapshot_dir", cfg.SnapshotDir); err != nil {
		return ChrootConfig{}, err
	}
	cfg.SnapshotDir = normalizeAndroidRuntimePath(cfg.SnapshotDir, runtime, legacySnapshotDir(runtime), filepath.Join(runtime.AndroidStateDir, "snapshots"))
	if value, ok := payload["snapshot_before_destructive"]; ok {
		cfg.SnapshotBeforeDestructive, err = validation.StrictBool(value, "snapshot_before_destructive")
		if err != nil {
			return ChrootConfig{}, err
		}
	}
	if cfg.ToolManifestDirs, err = pathsFromPayload(payload, repositories, "tool_manifest_dirs", "tool_manifests", cfg.ToolManifestDirs, runtime.Home); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.ToolScriptDirs, err = pathsFromPayload(payload, repositories, "tool_script_dirs", "tool_scripts", cfg.ToolScriptDirs, runtime.Home); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.AddonManifestDirs, err = pathsFromPayload(payload, repositories, "addon_manifest_dirs", "addon_manifests", cfg.AddonManifestDirs, runtime.Home); err != nil {
		return ChrootConfig{}, err
	}
	if cfg.AddonScriptDirs, err = pathsFromPayload(payload, repositories, "addon_script_dirs", "addon_scripts", cfg.AddonScriptDirs, runtime.Home); err != nil {
		return ChrootConfig{}, err
	}
	if value, ok := payload["service_dirs"]; ok {
		cfg.ServiceDirs, err = normalizePaths(value, runtime.Home)
		if err != nil {
			return ChrootConfig{}, err
		}
	}
	if cfg.ServiceStateDir, err = optionalString(payload, "service_state_dir", cfg.ServiceStateDir); err != nil {
		return ChrootConfig{}, err
	}
	cfg.ServiceStateDir = expandUser(cfg.ServiceStateDir, runtime.Home)
	if cfg.ServiceLogDir, err = optionalString(payload, "service_log_dir", cfg.ServiceLogDir); err != nil {
		return ChrootConfig{}, err
	}
	cfg.ServiceLogDir = expandUser(cfg.ServiceLogDir, runtime.Home)
	return cfg, nil
}

func normalizeMounts(value any) ([]BindMount, error) {
	if value == nil {
		return []BindMount{}, nil
	}
	if existing, ok := value.([]BindMount); ok {
		return cloneMounts(existing), nil
	}
	mounts := []BindMount{}
	switch typed := value.(type) {
	case map[string]any:
		for source, raw := range typed {
			switch definition := raw.(type) {
			case string:
				target, err := validation.RelativeChrootPathField(definition, "mount target for "+source)
				if err != nil {
					return nil, err
				}
				mounts = append(mounts, BindMount{Source: source, Target: target, Enabled: true})
			case map[string]any:
				rawTarget, ok := definition["target"]
				if !ok {
					return nil, fmt.Errorf("mount target for %s is required", source)
				}
				target, err := validation.RelativeChrootPathField(rawTarget, "mount target for "+source)
				if err != nil {
					return nil, err
				}
				enabled := true
				if rawEnabled, ok := definition["enabled"]; ok {
					enabled, err = validation.StrictBool(rawEnabled, "mount enabled for "+source)
					if err != nil {
						return nil, err
					}
				}
				readOnly := false
				if rawReadOnly, ok := definition["read_only"]; ok {
					readOnly, err = validation.StrictBool(rawReadOnly, "mount read_only for "+source)
					if err != nil {
						return nil, err
					}
				}
				mounts = append(mounts, BindMount{Source: source, Target: target, Enabled: enabled, ReadOnly: readOnly})
			default:
				return nil, errors.New("mount definition must be a string target or object")
			}
		}
	case []any:
		for _, raw := range typed {
			definition, ok := raw.(map[string]any)
			if !ok {
				return nil, errors.New("mount list entries must be objects")
			}
			source, err := requiredString(definition, "source")
			if err != nil {
				return nil, err
			}
			rawTarget, ok := definition["target"]
			if !ok {
				return nil, errors.New("mount target is required")
			}
			target, err := validation.RelativeChrootPathField(rawTarget, "mount target")
			if err != nil {
				return nil, err
			}
			enabled := true
			if rawEnabled, ok := definition["enabled"]; ok {
				enabled, err = validation.StrictBool(rawEnabled, "mount enabled")
				if err != nil {
					return nil, err
				}
			}
			readOnly := false
			if rawReadOnly, ok := definition["read_only"]; ok {
				readOnly, err = validation.StrictBool(rawReadOnly, "mount read_only")
				if err != nil {
					return nil, err
				}
			}
			mounts = append(mounts, BindMount{Source: source, Target: target, Enabled: enabled, ReadOnly: readOnly})
		}
	default:
		return nil, errors.New("mount configuration must be a mapping or list")
	}
	return mounts, nil
}

func normalizeStrings(value any) ([]string, error) {
	if value == nil {
		return []string{}, nil
	}
	items, ok := value.([]any)
	if !ok {
		if stringsValue, ok := value.([]string); ok {
			return append([]string(nil), stringsValue...), nil
		}
		return nil, errors.New("expected a list of strings")
	}
	result := make([]string, 0, len(items))
	for index, item := range items {
		text, ok := item.(string)
		if !ok {
			return nil, fmt.Errorf("expected string at index %d", index)
		}
		result = append(result, text)
	}
	return result, nil
}

func normalizePaths(value any, home string) ([]string, error) {
	if value == nil {
		return []string{}, nil
	}
	if text, ok := value.(string); ok {
		return []string{expandUser(text, home)}, nil
	}
	items, ok := value.([]any)
	if !ok {
		if values, ok := value.([]string); ok {
			result := make([]string, 0, len(values))
			for _, item := range values {
				result = append(result, expandUser(item, home))
			}
			return result, nil
		}
		return nil, errors.New("expected a list of paths")
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		text, ok := item.(string)
		if !ok {
			return nil, errors.New("path entries must be strings")
		}
		result = append(result, expandUser(text, home))
	}
	return result, nil
}

func pathsFromPayload(payload, repositories map[string]any, primary, legacy string, current []string, home string) ([]string, error) {
	if value, ok := payload[primary]; ok {
		return normalizePaths(value, home)
	}
	if value, ok := repositories[legacy]; ok {
		return normalizePaths(value, home)
	}
	return cloneStrings(current), nil
}

func optionalString(payload map[string]any, key, current string) (string, error) {
	value, ok := payload[key]
	if !ok {
		return current, nil
	}
	text, ok := value.(string)
	if !ok {
		return "", fmt.Errorf("%s must be a string", key)
	}
	return text, nil
}

func requiredString(payload map[string]any, key string) (string, error) {
	value, ok := payload[key]
	if !ok {
		return "", fmt.Errorf("%s is required", key)
	}
	text, ok := value.(string)
	if !ok {
		return "", fmt.Errorf("%s must be a string", key)
	}
	return text, nil
}

func normalizeOverrides(value any) (map[string]map[string]any, error) {
	if value == nil {
		return map[string]map[string]any{}, nil
	}
	mapping, ok := value.(map[string]any)
	if !ok {
		return nil, errors.New("chroot_overrides must be a mapping")
	}
	result := make(map[string]map[string]any, len(mapping))
	for name, raw := range mapping {
		entry, ok := raw.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("chroot_overrides.%s must be a mapping", name)
		}
		result[name] = cloneAnyMap(entry)
	}
	return result, nil
}

func expandUser(path, home string) string {
	if path == "~" {
		return home
	}
	if strings.HasPrefix(path, "~/") {
		return filepath.Join(home, strings.TrimPrefix(path, "~/"))
	}
	return path
}

func normalizeAndroidRuntimePath(path string, runtime RuntimeContext, legacy, stable string) string {
	if runtime.Android && filepath.Clean(path) == filepath.Clean(legacy) {
		return stable
	}
	return path
}

func legacyConfigPath(runtime RuntimeContext) string {
	return filepath.Join(runtime.LegacyHome, ".config", "chrootctl", "config.json")
}
func legacyDatabasePath(runtime RuntimeContext) string {
	return filepath.Join(runtime.LegacyHome, ".local", "share", "chrootctl", "chroots.sqlite3")
}
func legacySnapshotDir(runtime RuntimeContext) string {
	return filepath.Join(runtime.LegacyHome, ".local", "share", "chrootctl", "snapshots")
}

func MigrateAndroidRuntimeLayout(runtime RuntimeContext, counter ChrootCounter) error {
	runtime = normalizeRuntime(runtime)
	if !runtime.Android {
		return nil
	}
	if err := os.MkdirAll(runtime.AndroidStateDir, 0o755); err != nil {
		return err
	}
	if err := copyIfMissing(legacyConfigPath(runtime), DefaultConfigPath(runtime)); err != nil {
		return err
	}
	if counter != nil {
		legacyCount := safeCount(counter, legacyDatabasePath(runtime))
		stablePath := filepath.Join(runtime.AndroidStateDir, "chroots.sqlite3")
		stableCount := safeCount(counter, stablePath)
		if legacyCount > 0 && stableCount == 0 {
			legacyPath := legacyDatabasePath(runtime)
			info, statErr := os.Stat(legacyPath)
			if statErr != nil && !errors.Is(statErr, os.ErrNotExist) {
				return statErr
			}
			if statErr == nil && info.Mode().IsRegular() {
				if err := os.MkdirAll(filepath.Dir(stablePath), 0o755); err != nil {
					return err
				}
				if err := copyFile(legacyPath, stablePath, info.Mode()); err != nil {
					return err
				}
			}
		}
	}
	return mergeTreeMissing(legacySnapshotDir(runtime), filepath.Join(runtime.AndroidStateDir, "snapshots"))
}

func safeCount(counter ChrootCounter, path string) int {
	count, err := counter(path)
	if err != nil {
		return 0
	}
	return count
}

func copyIfMissing(source, target string) error {
	info, err := os.Stat(source)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return nil
	}
	if _, targetErr := os.Stat(target); targetErr == nil {
		return nil
	} else if !errors.Is(targetErr, os.ErrNotExist) {
		return targetErr
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return err
	}
	return copyFile(source, target, info.Mode())
}

func copyFile(source, target string, mode os.FileMode) error {
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode.Perm())
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(out, in)
	closeErr := out.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

func mergeTreeMissing(source, target string) error {
	if _, err := os.Stat(source); errors.Is(err, os.ErrNotExist) {
		return nil
	} else if err != nil {
		return err
	}
	if err := os.MkdirAll(target, 0o755); err != nil {
		return err
	}
	return filepath.WalkDir(source, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		destination := filepath.Join(target, rel)
		if entry.IsDir() {
			return os.MkdirAll(destination, 0o755)
		}
		if _, err := os.Stat(destination); err == nil {
			return nil
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
			return err
		}
		return copyFile(path, destination, info.Mode())
	})
}

func decodeObject(data []byte) (map[string]any, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return nil, errors.New("config JSON contains trailing data")
	}
	mapping, ok := value.(map[string]any)
	if !ok {
		return nil, errors.New("config root must be a JSON object")
	}
	return mapping, nil
}

func cloneMounts(values []BindMount) []BindMount {
	result := make([]BindMount, len(values))
	copy(result, values)
	return result
}
func cloneStrings(values []string) []string {
	result := make([]string, len(values))
	copy(result, values)
	return result
}
func cloneAnyMap(value map[string]any) map[string]any {
	result := make(map[string]any, len(value))
	for k, v := range value {
		result[k] = v
	}
	return result
}
func cloneOverrides(value map[string]map[string]any) map[string]map[string]any {
	result := make(map[string]map[string]any, len(value))
	for k, v := range value {
		result[k] = cloneAnyMap(v)
	}
	return result
}
