package services

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"chrootctl/internal/config"
	"chrootctl/internal/logging"
	"chrootctl/internal/registry"
)

func testContainer(t *testing.T) *Container {
	t.Helper()
	root := t.TempDir()
	cfg := config.Default(config.RuntimeContext{Home: root, Android: false})
	cfg.ChrootRoot = filepath.Join(root, "chroots")
	cfg.DatabasePath = filepath.Join(root, "state", "chroots.sqlite3")
	cfg.LogFile = filepath.Join(root, "logs", "chrootctl.log")
	cfg.SnapshotDir = filepath.Join(root, "snapshots")
	cfg.ServiceStateDir = filepath.Join(root, "state", "services")
	cfg.ServiceLogDir = filepath.Join(root, "logs", "services")
	cfg.ServiceDirs = []string{filepath.Join(root, "services")}
	for _, p := range []string{cfg.ChrootRoot, filepath.Dir(cfg.DatabasePath), filepath.Dir(cfg.LogFile), cfg.SnapshotDir, cfg.ServiceStateDir, cfg.ServiceLogDir, cfg.ServiceDirs[0]} {
		if e := os.MkdirAll(p, 0755); e != nil {
			t.Fatal(e)
		}
	}
	reg, e := registry.Open(cfg.DatabasePath)
	if e != nil {
		t.Fatal(e)
	}
	logger := logging.Configure(cfg.LogFile, false)
	c, e := NewWith(cfg, reg, logger, false)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c
}
func TestContainerWiresSharedServices(t *testing.T) {
	ctx := context.Background()
	c := testContainer(t)
	arch := "arm64"
	if e := c.Registry.Upsert(ctx, registry.ChrootInput{Name: "work", Distro: "ubuntu", Path: filepath.Join(c.BaseConfig.ChrootRoot, "work"), Arch: &arch, Phase: "registered", Metadata: map[string]any{"profile": "dev"}}); e != nil {
		t.Fatal(e)
	}
	rows, e := c.Chroots().List(ctx)
	if e != nil || len(rows) != 1 || rows[0].Name != "work" {
		t.Fatalf("chroots=%v err=%v", rows, e)
	}
	if _, e = c.Audit().Record(ctx, "test.event", "work", "ok", "service wiring", "", map[string]string{"source": "go09"}); e != nil {
		t.Fatal(e)
	}
	events, e := c.Audit().Recent(ctx, 10)
	if e != nil || len(events) != 1 || events[0].EventType != "test.event" {
		t.Fatalf("events=%v err=%v", events, e)
	}
	preview, e := c.Preview().Upgrade(ctx, "work")
	if e != nil || preview["kind"] != "upgrade" {
		t.Fatalf("preview=%v err=%v", preview, e)
	}
	if got := c.ReleaseReadiness().Status(); got["ready"] != false {
		t.Fatalf("missing release evidence must fail closed: %v", got)
	}
}
func TestRepairServiceRoundTrip(t *testing.T) {
	ctx := context.Background()
	c := testContainer(t)
	p := filepath.Join(c.BaseConfig.ChrootRoot, "recovered")
	if e := os.MkdirAll(p, 0755); e != nil {
		t.Fatal(e)
	}
	items, e := c.Repair().PreviewItems(ctx)
	if e != nil || len(items) != 1 || items[0]["kind"] != "missing-record" {
		t.Fatalf("items=%v err=%v", items, e)
	}
	res, e := c.Repair().ApplyPlan(ctx, []map[string]string{{"item_id": "chroot:recovered", "action": "register"}})
	if e != nil {
		t.Fatal(e)
	}
	if len(res.RepairedRecords) != 1 || res.RepairedRecords[0] != "recovered" {
		t.Fatalf("result=%+v", res)
	}
	row, e := c.Registry.Get(ctx, "recovered")
	if e != nil || row == nil || row.Path != p {
		t.Fatalf("row=%+v err=%v", row, e)
	}
}
func TestServiceUnitParser(t *testing.T) {
	p := filepath.Join(t.TempDir(), "demo.service")
	text := "[Unit]\nDescription=Demo\nAfter=network.target\n[Service]\nChroot=work\nUser=alice\nExecStart=echo hello\nEnvironment=FOO=bar\n[Install]\nWantedBy=boot.target\n"
	if e := os.WriteFile(p, []byte(text), 0644); e != nil {
		t.Fatal(e)
	}
	u, e := loadUnit(p)
	if e != nil {
		t.Fatal(e)
	}
	if u.Name != "demo.service" || u.Chroot != "work" || u.ExecStart != "echo hello" || u.Environment["FOO"] != "bar" {
		t.Fatalf("unit=%+v", u)
	}
}

func TestServiceBoundChrootRejectsOverride(t *testing.T) {
	s := &UnitService{}
	if _, err := s.bound(ServiceUnit{Name: "demo.service", Chroot: "work"}, "other"); err == nil {
		t.Fatal("expected bound-chroot mismatch to fail")
	}
}

func TestBootLayersIncludeRequiresAndRespectAfter(t *testing.T) {
	units := map[string]ServiceUnit{
		"db.service":  {Name: "db.service", Chroot: "work"},
		"api.service": {Name: "api.service", Chroot: "work", Requires: []string{"db.service"}, After: []string{"db.service"}},
		"web.service": {Name: "web.service", Chroot: "work", Requires: []string{"api.service"}, After: []string{"api.service"}},
	}
	layers, err := buildBootLayers(units, func(chroot, unit string) bool { return unit == "web.service" })
	if err != nil {
		t.Fatal(err)
	}
	if len(layers) != 3 || layers[0][0].Name != "db.service" || layers[1][0].Name != "api.service" || layers[2][0].Name != "web.service" {
		t.Fatalf("unexpected boot layers: %#v", layers)
	}
}

func TestBootLayersParallelizeIndependentUnits(t *testing.T) {
	units := map[string]ServiceUnit{
		"a.service": {Name: "a.service", Chroot: "work"},
		"b.service": {Name: "b.service", Chroot: "work"},
	}
	layers, err := buildBootLayers(units, func(chroot, unit string) bool { return true })
	if err != nil {
		t.Fatal(err)
	}
	if len(layers) != 1 || len(layers[0]) != 2 {
		t.Fatalf("independent services should share one layer: %#v", layers)
	}
}

func TestBootLayersRejectCycle(t *testing.T) {
	units := map[string]ServiceUnit{
		"a.service": {Name: "a.service", Chroot: "work", After: []string{"b.service"}},
		"b.service": {Name: "b.service", Chroot: "work", After: []string{"a.service"}},
	}
	if _, err := buildBootLayers(units, func(chroot, unit string) bool { return true }); err == nil {
		t.Fatal("expected dependency cycle to fail")
	}
}

func TestServiceStartCommandHonorsWorkingDirectoryAndRestart(t *testing.T) {
	u := ServiceUnit{ExecStart: "run-server", WorkingDirectory: "/home/me/a b", Restart: "on-failure", RestartSec: 5}
	got := serviceStartCommand(u)
	for _, want := range []string{"cd -- '/home/me/a b'", "run-server", "sleep 5", "rc=$?"} {
		if !strings.Contains(got, want) {
			t.Fatalf("command %q missing %q", got, want)
		}
	}
}
