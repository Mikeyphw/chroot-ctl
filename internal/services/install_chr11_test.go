package services

import (
	"chrootctl/internal/config"
	"chrootctl/internal/install"
	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	"context"
	"os"
	"strings"
	"testing"
)

func newCHR11InstallService(t *testing.T) *InstallService {
	t.Helper()
	cfg := config.Default(config.RuntimeContext{Home: t.TempDir()})
	cfg.ChrootRoot = t.TempDir()
	cfg.DatabasePath = t.TempDir() + "/chroots.sqlite3"
	reg, err := registry.Open(cfg.DatabasePath)
	if err != nil {
		t.Fatal(err)
	}
	c, err := NewWith(cfg, reg, nil, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c.Install()
}

func TestCHR11InstallFormStateUsesAuthoritativeBackendOptions(t *testing.T) {
	svc := newCHR11InstallService(t)
	state, err := svc.InstallFormState(context.Background(), "", "arch")
	if err != nil {
		t.Fatal(err)
	}
	if got := optionIDsFromState(state, "distros"); strings.Join(got, ",") != "ubuntu,arch" {
		t.Fatalf("unexpected distro options: %v", got)
	}
	if got := optionIDsFromState(state, "architectures"); strings.Join(got, ",") != "arm64" {
		t.Fatalf("arch form must not expose amd64: %v", got)
	}
	if got := optionIDsFromState(state, "profiles"); !contains(got, "dev") || contains(got, "developer") {
		t.Fatalf("unexpected profile options: %v", got)
	}
	if got := optionIDsFromState(state, "desktops"); !contains(got, "xfce4") || contains(got, "xfce") {
		t.Fatalf("unexpected desktop options: %v", got)
	}
}

func TestCHR11InstallPreviewShowsExactNormalizedPlan(t *testing.T) {
	svc := newCHR11InstallService(t)
	preview := svc.PreviewInstall(model.InstallRequest{Distro: "ubuntu", Name: "", Username: "mike", Arch: "arm64", Preset: testStringPtr("desktop-xfce"), Phase: testStringPtr("extract")})
	if ok, _ := preview["ok"].(bool); !ok {
		t.Fatalf("expected ok preview: %+v", preview["blocking"])
	}
	request := preview["request"].(map[string]any)
	if request["profile"] != "xfce4" || request["desktop"] != "xfce4" || request["preset"] != "desktop-xfce4" {
		t.Fatalf("preview did not show exact normalized plan: %+v", request)
	}
}

func TestCHR11ValidateRejectsUnsafeFallbackValues(t *testing.T) {
	svc := newCHR11InstallService(t)
	plan := svc.ValidateRequest(model.InstallRequest{Distro: "debian", Name: "demo", Username: "mike", Arch: "arm64", Profile: testStringPtr("developer"), Desktop: testStringPtr("xfce")})
	if ok, _ := plan["ok"].(bool); ok {
		t.Fatalf("expected invalid plan: %+v", plan)
	}
	blocking := plan["blocking"].([]map[string]string)
	for _, code := range []string{"invalid_distro", "invalid_profile", "invalid_desktop"} {
		found := false
		for _, issue := range blocking {
			if issue["code"] == code {
				found = true
			}
		}
		if !found {
			t.Fatalf("missing %s in %+v", code, blocking)
		}
	}
}

func optionIDsFromState(state map[string]any, key string) []string {
	switch rows := state[key].(type) {
	case []install.Option:
		out := make([]string, 0, len(rows))
		for _, row := range rows {
			out = append(out, row.ID)
		}
		return out
	case []map[string]any:
		out := make([]string, 0, len(rows))
		for _, row := range rows {
			out = append(out, row["id"].(string))
		}
		return out
	case []interface{}:
		out := make([]string, 0, len(rows))
		for _, row := range rows {
			if m, ok := row.(map[string]any); ok {
				out = append(out, m["id"].(string))
			}
		}
		return out
	default:
		return nil
	}
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func testStringPtr(value string) *string {
	return &value
}

func TestCHR11InstallPreviewBlocksExistingUnownedTarget(t *testing.T) {
	svc := newCHR11InstallService(t)
	root := svc.C.BaseConfig.ChrootRoot + "/demo"
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	plan, err := svc.C.Preview().Install(context.Background(), model.InstallRequest{Distro: "ubuntu", Name: "demo", Username: "mike", Arch: "arm64", Phase: testStringPtr("extract")})
	if err != nil {
		t.Fatal(err)
	}
	if ok, _ := plan["ok"].(bool); ok {
		t.Fatalf("preview must block existing unowned target: %+v", plan)
	}
	blocking, _ := plan["blocking"].([]map[string]string)
	found := false
	for _, issue := range blocking {
		if issue["code"] == "target_collision" {
			found = true
		}
	}
	if !found {
		t.Fatalf("missing target_collision: %+v", blocking)
	}
}

func TestCHR11InstallPreviewBlocksAlreadyRegisteredName(t *testing.T) {
	svc := newCHR11InstallService(t)
	ctx := context.Background()
	if err := svc.C.Registry.SetQueryOnly(ctx, false); err != nil {
		t.Fatal(err)
	}
	if err := svc.C.Registry.Upsert(ctx, registry.ChrootInput{Name: "demo", Distro: "ubuntu", Arch: testStringPtr("arm64"), Path: svc.C.BaseConfig.ChrootRoot + "/demo", Phase: "finalize", Installed: true}); err != nil {
		t.Fatal(err)
	}
	if err := svc.C.Registry.SetQueryOnly(ctx, true); err != nil {
		t.Fatal(err)
	}
	plan, err := svc.C.Preview().Install(ctx, model.InstallRequest{Distro: "ubuntu", Name: "demo", Username: "mike", Arch: "arm64", Phase: testStringPtr("extract")})
	if err != nil {
		t.Fatal(err)
	}
	if ok, _ := plan["ok"].(bool); ok {
		t.Fatalf("preview must block registered create target: %+v", plan)
	}
	blocking, _ := plan["blocking"].([]map[string]string)
	found := false
	for _, issue := range blocking {
		if issue["code"] == "target_registered" {
			found = true
		}
	}
	if !found {
		t.Fatalf("missing target_registered: %+v", blocking)
	}
}
