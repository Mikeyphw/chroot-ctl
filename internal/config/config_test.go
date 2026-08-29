package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

type foundationsConfigFixture struct {
	Config struct {
		DefaultNonAndroid map[string]any `json:"defaultNonAndroid"`
		DefaultAndroid    map[string]any `json:"defaultAndroid"`
		CustomPayload     map[string]any `json:"customPayload"`
		CustomResolved    map[string]any `json:"customResolved"`
		WorkResolved      map[string]any `json:"workResolved"`
		ShellResolution   map[string]any `json:"shellResolution"`
	} `json:"config"`
}

func foundationsFixturePath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "migration", "contracts", "v1", "foundations.json"))
}

func loadFoundationsConfig(t *testing.T) foundationsConfigFixture {
	t.Helper()
	data, err := os.ReadFile(foundationsFixturePath(t))
	if err != nil {
		t.Fatal(err)
	}
	var fixture foundationsConfigFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	return fixture
}

func TestDefaultConfigParity(t *testing.T) {
	fixture := loadFoundationsConfig(t)
	nonAndroidRuntime := RuntimeContext{Android: false, Home: "/home/tester", AndroidStateDir: AndroidStateRoot, LegacyHome: LegacyTermuxHome}
	androidRuntime := RuntimeContext{Android: true, Home: "/home/tester", AndroidStateDir: AndroidStateRoot, LegacyHome: LegacyTermuxHome}
	assertConfigContract(t, Default(nonAndroidRuntime), nonAndroidRuntime, fixture.Config.DefaultNonAndroid)
	assertConfigContract(t, Default(androidRuntime), androidRuntime, fixture.Config.DefaultAndroid)
}

func TestCustomPayloadAndChrootOverrideParity(t *testing.T) {
	fixture := loadFoundationsConfig(t)
	runtime := RuntimeContext{Home: "/home/tester", AndroidStateDir: AndroidStateRoot, LegacyHome: LegacyTermuxHome}
	base := Default(runtime)
	base.DatabasePath = "/tmp/base/chroots.sqlite3"
	base.SnapshotDir = "/tmp/base/snapshots"
	base.ServiceDirs = []string{"/tmp/base/services"}
	base.ServiceStateDir = "/tmp/base/run/services"
	base.ServiceLogDir = "/tmp/base/logs/services"
	custom, err := ApplyPayload(base, fixture.Config.CustomPayload, runtime)
	if err != nil {
		t.Fatal(err)
	}
	overrides, err := normalizeOverrides(fixture.Config.CustomPayload["chroot_overrides"])
	if err != nil {
		t.Fatal(err)
	}
	custom.ChrootOverrides = overrides
	assertConfigContract(t, custom, runtime, fixture.Config.CustomResolved)

	work, err := custom.ForChroot("work", runtime)
	if err != nil {
		t.Fatal(err)
	}
	assertConfigContract(t, work, runtime, fixture.Config.WorkResolved)
	if got := custom.ResolvedShell(map[string]bool{custom.ShellPath: true}); got != fixture.Config.ShellResolution["configured"] {
		t.Fatalf("configured shell = %q", got)
	}
	if got := custom.ResolvedShell(map[string]bool{"/bin/bash": true}); got != fixture.Config.ShellResolution["bashFallback"] {
		t.Fatalf("bash fallback = %q", got)
	}
	if got := custom.ResolvedShell(nil); got != fixture.Config.ShellResolution["configuredFallback"] {
		t.Fatalf("configured fallback = %q", got)
	}
}

func TestLoadAndAndroidLayoutMigration(t *testing.T) {
	root := t.TempDir()
	runtime := RuntimeContext{
		Android:         true,
		Home:            filepath.Join(root, "home"),
		AndroidStateDir: filepath.Join(root, "adb", "chrootctl"),
		LegacyHome:      filepath.Join(root, "termux"),
	}
	legacyConfig := legacyConfigPath(runtime)
	legacyDB := legacyDatabasePath(runtime)
	legacySnapshots := legacySnapshotDir(runtime)
	if err := os.MkdirAll(filepath.Dir(legacyConfig), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(legacyDB), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(legacySnapshots, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(legacyConfig, []byte(`{"username":"mike","database_path":"`+legacyDB+`","snapshot_dir":"`+legacySnapshots+`"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(legacyDB, []byte("sqlite-fixture"), 0o600); err != nil {
		t.Fatal(err)
	}
	stableDB := filepath.Join(runtime.AndroidStateDir, "chroots.sqlite3")
	if err := os.MkdirAll(filepath.Dir(stableDB), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(stableDB, []byte("nonempty-but-zero-row-stable-db"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(legacySnapshots, "snap1.tar.zst"), []byte("snapshot"), 0o600); err != nil {
		t.Fatal(err)
	}

	counter := func(path string) (int, error) {
		if filepath.Clean(path) == filepath.Clean(legacyDB) {
			return 1, nil
		}
		return 0, nil
	}
	cfg, err := Load("", WithRuntime(runtime), WithChrootCounter(counter))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.DatabasePath != filepath.Join(runtime.AndroidStateDir, "chroots.sqlite3") {
		t.Fatalf("database path = %q", cfg.DatabasePath)
	}
	if cfg.SnapshotDir != filepath.Join(runtime.AndroidStateDir, "snapshots") {
		t.Fatalf("snapshot dir = %q", cfg.SnapshotDir)
	}
	stableData, err := os.ReadFile(stableDB)
	if err != nil {
		t.Fatal(err)
	}
	if string(stableData) != "sqlite-fixture" {
		t.Fatalf("stable DB was not replaced from populated legacy DB: %q", stableData)
	}
	for _, path := range []string{
		DefaultConfigPath(runtime),
		stableDB,
		filepath.Join(runtime.AndroidStateDir, "snapshots", "snap1.tar.zst"),
	} {
		if _, err := os.Stat(path); err != nil {
			t.Errorf("migrated path %s: %v", path, err)
		}
	}
}

func TestLoadRejectsInvalidJSONAndUnsafeOverrideName(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte("{not-json}"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path, WithRuntime(RuntimeContext{Home: "/home/tester"})); err == nil {
		t.Fatal("invalid JSON unexpectedly accepted")
	}
	cfg := Default(RuntimeContext{Home: "/home/tester"})
	if _, err := cfg.ForChroot("../bad", RuntimeContext{Home: "/home/tester"}); err == nil || err.Error() != "chroot name must be a safe basename" {
		t.Fatalf("unsafe override error = %v", err)
	}
}

func assertConfigContract(t *testing.T, cfg ChrootConfig, runtime RuntimeContext, want map[string]any) {
	t.Helper()
	got := configContractPayload(cfg, runtime)
	if _, ok := want["default_config_path"]; ok {
		got["default_config_path"] = DefaultConfigPath(runtime)
	}
	gotBytes, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	wantBytes, err := json.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	var gotValue, wantValue any
	if err := json.Unmarshal(gotBytes, &gotValue); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(wantBytes, &wantValue); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(gotValue, wantValue) {
		t.Fatalf("config mismatch\n got: %s\nwant: %s", gotBytes, wantBytes)
	}
}

func configContractPayload(cfg ChrootConfig, runtime RuntimeContext) map[string]any {
	payload := map[string]any{
		"chroot_root": cfg.ChrootRoot, "distro_name": cfg.DistroName, "username": cfg.Username,
		"target_arch": cfg.TargetArch, "termux_home": cfg.TermuxHome, "termux_prefix": cfg.TermuxPrefix,
		"log_file": cfg.LogFile, "database_path": cfg.DatabasePath, "shell_path": cfg.ShellPath,
		"mount_data_with_dev_suid": cfg.MountDataWithDevSuid, "dev_shm_size": cfg.DevShmSize,
		"media_mounts": cfg.MediaMounts, "extra_bind_mounts": cfg.ExtraBindMounts, "extra_packages": cfg.ExtraPackages,
		"locale": cfg.Locale, "dns_servers": cfg.DNSServers, "post_install_hooks": cfg.PostInstallHooks,
		"install_profile": cfg.InstallProfile, "snapshot_dir": cfg.SnapshotDir,
		"snapshot_before_destructive": cfg.SnapshotBeforeDestructive,
		"tool_manifest_dirs":          cfg.ToolManifestDirs, "tool_script_dirs": cfg.ToolScriptDirs,
		"addon_manifest_dirs": cfg.AddonManifestDirs, "addon_script_dirs": cfg.AddonScriptDirs,
		"service_dirs": cfg.ServiceDirs, "service_state_dir": cfg.ServiceStateDir, "service_log_dir": cfg.ServiceLogDir,
		"chroot_overrides": cfg.ChrootOverrides,
		"derived":          map[string]any{"chroot_base": cfg.ChrootBase(), "user_home_in_chroot": cfg.UserHomeInChroot(), "termux_home_in_chroot": cfg.TermuxHomeInChroot()},
	}
	return payload
}

func TestConfigJSONFieldNamesMatchFrozenPythonDataclass(t *testing.T) {
	contractPath := filepath.Join(filepath.Dir(foundationsFixturePath(t)), "persistence.json")
	data, err := os.ReadFile(contractPath)
	if err != nil {
		t.Fatal(err)
	}
	var contract struct {
		Config struct {
			Fields []struct {
				Name string `json:"name"`
			} `json:"fields"`
		} `json:"config"`
	}
	if err := json.Unmarshal(data, &contract); err != nil {
		t.Fatal(err)
	}
	typ := reflect.TypeOf(ChrootConfig{})
	got := make([]string, 0, typ.NumField())
	for index := 0; index < typ.NumField(); index++ {
		tag := typ.Field(index).Tag.Get("json")
		if comma := strings.IndexByte(tag, ','); comma >= 0 {
			tag = tag[:comma]
		}
		got = append(got, tag)
	}
	want := make([]string, 0, len(contract.Config.Fields))
	for _, field := range contract.Config.Fields {
		want = append(want, field.Name)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("config fields = %#v, want %#v", got, want)
	}
}
