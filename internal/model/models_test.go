package model

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"testing"
)

type foundationsFixture struct {
	Models struct {
		FieldNames map[string][]string `json:"fieldNames"`
		Samples    map[string]struct {
			Display   map[string]string `json:"display"`
			State     map[string]any    `json:"state"`
			Success   *bool             `json:"success"`
			Text      string            `json:"text"`
			NextSteps []string          `json:"nextSteps"`
		} `json:"samples"`
	} `json:"models"`
}

func foundationsPath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "migration", "contracts", "v1", "foundations.json"))
}

func TestPythonModelFieldNamesAreMirrored(t *testing.T) {
	data, err := os.ReadFile(foundationsPath(t))
	if err != nil {
		t.Fatal(err)
	}
	var fixture foundationsFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	types := map[string]reflect.Type{
		"OperationResult":              reflect.TypeOf(OperationResult{}),
		"ChrootRemovalResult":          reflect.TypeOf(ChrootRemovalResult{}),
		"ChrootRenameResult":           reflect.TypeOf(ChrootRenameResult{}),
		"ChrootExportResult":           reflect.TypeOf(ChrootExportResult{}),
		"ChrootImportResult":           reflect.TypeOf(ChrootImportResult{}),
		"PackageDiffResult":            reflect.TypeOf(PackageDiffResult{}),
		"ChrootArchiveInspection":      reflect.TypeOf(ChrootArchiveInspection{}),
		"SnapshotRecord":               reflect.TypeOf(SnapshotRecord{}),
		"SnapshotActionResult":         reflect.TypeOf(SnapshotActionResult{}),
		"RegistryRepairResult":         reflect.TypeOf(RegistryRepairResult{}),
		"AuditEvent":                   reflect.TypeOf(AuditEvent{}),
		"SupportBundleResult":          reflect.TypeOf(SupportBundleResult{}),
		"ChrootUserDetails":            reflect.TypeOf(ChrootUserDetails{}),
		"ChrootUserCreateResult":       reflect.TypeOf(ChrootUserCreateResult{}),
		"ChrootUserRemoveResult":       reflect.TypeOf(ChrootUserRemoveResult{}),
		"ChrootUserPasswordResult":     reflect.TypeOf(ChrootUserPasswordResult{}),
		"ChrootUserShellResult":        reflect.TypeOf(ChrootUserShellResult{}),
		"ChrootUserSudoResult":         reflect.TypeOf(ChrootUserSudoResult{}),
		"CatalogApplyResult":           reflect.TypeOf(CatalogApplyResult{}),
		"InstallExtractResult":         reflect.TypeOf(InstallExtractResult{}),
		"InstallBootstrapResult":       reflect.TypeOf(InstallBootstrapResult{}),
		"InstallDesktopResult":         reflect.TypeOf(InstallDesktopResult{}),
		"InstallFinalizeResult":        reflect.TypeOf(InstallFinalizeResult{}),
		"InstallAlreadyCompleteResult": reflect.TypeOf(InstallAlreadyCompleteResult{}),
		"UpgradeResult":                reflect.TypeOf(UpgradeResult{}),
		"UserIdStatus":                 reflect.TypeOf(UserIdStatus{}),
		"UserIdSyncResult":             reflect.TypeOf(UserIdSyncResult{}),
		"ChrootRecord":                 reflect.TypeOf(ChrootRecord{}),
		"ChrootDetails":                reflect.TypeOf(ChrootDetails{}),
		"CheckRow":                     reflect.TypeOf(CheckRow{}),
		"LogLink":                      reflect.TypeOf(LogLink{}),
		"LogEntry":                     reflect.TypeOf(LogEntry{}),
		"LogSnapshot":                  reflect.TypeOf(LogSnapshot{}),
		"DashboardSummary":             reflect.TypeOf(DashboardSummary{}),
		"InstallWizardDefaults":        reflect.TypeOf(InstallWizardDefaults{}),
		"InstallRequest":               reflect.TypeOf(InstallRequest{}),
		"InstallRunResult":             reflect.TypeOf(InstallRunResult{}),
		"SessionActionResult":          reflect.TypeOf(SessionActionResult{}),
		"DashboardChrootCard":          reflect.TypeOf(DashboardChrootCard{}),
		"AppBuildResult":               reflect.TypeOf(AppBuildResult{}),
	}
	if len(types) != len(fixture.Models.FieldNames) {
		t.Fatalf("model count = %d, Python contract = %d", len(types), len(fixture.Models.FieldNames))
	}
	for name, want := range fixture.Models.FieldNames {
		typ, ok := types[name]
		if !ok {
			t.Errorf("missing Go model %s", name)
			continue
		}
		got := make([]string, 0, typ.NumField())
		for i := 0; i < typ.NumField(); i++ {
			tag := typ.Field(i).Tag.Get("json")
			if comma := strings.IndexByte(tag, 44); comma >= 0 {
				tag = tag[:comma]
			}
			if tag != "" && tag != "-" {
				got = append(got, tag)
			}
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s fields = %#v, want %#v", name, got, want)
		}
	}
}

func TestModelSampleParity(t *testing.T) {
	data, err := os.ReadFile(foundationsPath(t))
	if err != nil {
		t.Fatal(err)
	}
	var fixture foundationsFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	op := OperationResult{}
	op.AddSuccess()
	op.AddFailure("boom")
	op.AddSkipped()
	if !reflect.DeepEqual(op.DisplayMap(), fixture.Models.Samples["operationResult"].Display) {
		t.Fatalf("operation display = %#v", op.DisplayMap())
	}
	session := SessionActionResult{Action: "restart", Target: "androidos", ExitCode: 0, NextSteps: []string{"inspect logs"}}
	if !reflect.DeepEqual(session.DisplayMap(), fixture.Models.Samples["sessionAction"].Display) {
		t.Fatalf("session display = %#v", session.DisplayMap())
	}
	info, warn := "INFO", "WARN"
	log := LogSnapshot{LogFile: "/tmp/chrootctl.log", Level: &info, Lines: []string{"fallback"}, Entries: []LogEntry{{Line: "line one", Level: &info}, {Line: "line two", Level: &warn}}}
	if log.Text() != fixture.Models.Samples["logSnapshot"].Text || !reflect.DeepEqual(log.DisplayMap(), fixture.Models.Samples["logSnapshot"].Display) {
		t.Fatalf("log sample mismatch: text=%q display=%#v", log.Text(), log.DisplayMap())
	}
	build := AppBuildResult{ArtifactName: "module.zip", ArtifactPath: "/tmp/module.zip", OutputDir: "/tmp", StartupTargets: []string{"androidos"}}
	if !reflect.DeepEqual(build.NextSteps(), fixture.Models.Samples["appBuild"].NextSteps) || !reflect.DeepEqual(build.DisplayMap(), fixture.Models.Samples["appBuild"].Display) {
		t.Fatalf("app build sample mismatch")
	}
}

func TestModelBehaviorHelpers(t *testing.T) {
	result := OperationResult{}
	result.AddSuccess()
	result.AddFailure("boom")
	result.AddSkipped()
	if result.Success != 1 || result.Failed != 1 || result.Skipped != 1 || !reflect.DeepEqual(result.Errors, []string{"boom"}) {
		t.Fatalf("operation result = %#v", result)
	}
	if !(SessionActionResult{ExitCode: 0}).SuccessValue() {
		t.Fatal("exit code 0 must be success")
	}
	if (SessionActionResult{ExitCode: 7}).SuccessValue() {
		t.Fatal("non-zero exit code must fail")
	}
	snapshot := LogSnapshot{Lines: []string{"fallback"}, Entries: []LogEntry{{Line: "one"}, {Line: "two"}}}
	if got := snapshot.Text(); got != "one\ntwo" {
		t.Fatalf("snapshot text = %q", got)
	}
	if got := (AppBuildResult{ArtifactName: "module.zip"}).NextSteps(); !reflect.DeepEqual(got, []string{"Download artifact: module.zip"}) {
		t.Fatalf("next steps = %#v", got)
	}
	keys := make([]string, 0, len(typesForDefaults()))
	for key := range typesForDefaults() {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	if len(keys) == 0 {
		t.Fatal("default constructor coverage unexpectedly empty")
	}
}

func typesForDefaults() map[string]any {
	return map[string]any{
		"ChrootImportResult":           NewChrootImportResult(),
		"ChrootArchiveInspection":      NewChrootArchiveInspection(),
		"InstallExtractResult":         NewInstallExtractResult(),
		"InstallBootstrapResult":       NewInstallBootstrapResult(),
		"InstallDesktopResult":         NewInstallDesktopResult(),
		"InstallFinalizeResult":        NewInstallFinalizeResult(),
		"InstallAlreadyCompleteResult": NewInstallAlreadyCompleteResult(),
		"InstallRequest":               NewInstallRequest(),
	}
}
