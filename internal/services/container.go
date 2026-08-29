package services

import (
	"context"
	"fmt"
	"path/filepath"

	"chrootctl/internal/catalog"
	"chrootctl/internal/config"
	"chrootctl/internal/controller"
	"chrootctl/internal/logging"
	"chrootctl/internal/operations"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"chrootctl/internal/users"
	"chrootctl/internal/validation"
)

type Runtime struct {
	Config     config.ChrootConfig
	Runner     *sys.Runner
	Controller *controller.Controller
	Users      *users.Manager
}

type Container struct {
	BaseConfig config.ChrootConfig
	Registry   *registry.Registry
	Logger     *logging.Logger
	Operations *operations.Manager
	DryRun     bool
}

func New(configPath string, dryRun, verbose bool) (*Container, error) {
	cfg, err := config.Load(configPath, config.WithChrootCounter(registry.CountChroots))
	if err != nil {
		return nil, err
	}
	reg, err := registry.Open(cfg.DatabasePath)
	if err != nil {
		return nil, err
	}
	logger := logging.Configure(cfg.LogFile, verbose)
	ops, err := operations.NewManager(filepath.Join(filepath.Dir(cfg.DatabasePath), "operations"), false)
	if err != nil {
		reg.Close()
		logger.Close()
		return nil, err
	}
	return &Container{BaseConfig: cfg, Registry: reg, Logger: logger, Operations: ops, DryRun: dryRun}, nil
}
func NewWith(cfg config.ChrootConfig, reg *registry.Registry, logger *logging.Logger, dryRun bool) (*Container, error) {
	if reg == nil {
		return nil, fmt.Errorf("services registry is nil")
	}
	ops, err := operations.NewManager(filepath.Join(filepath.Dir(cfg.DatabasePath), "operations"), false)
	if err != nil {
		return nil, err
	}
	return &Container{BaseConfig: cfg, Registry: reg, Logger: logger, Operations: ops, DryRun: dryRun}, nil
}
func (c *Container) Close() error {
	var first error
	if c.Registry != nil {
		first = c.Registry.Close()
	}
	if c.Logger != nil {
		if e := c.Logger.Close(); first == nil {
			first = e
		}
	}
	return first
}
func (c *Container) ConfigFor(name, username string) (config.ChrootConfig, error) {
	cfg := c.BaseConfig
	if name != "" {
		safe, e := validation.ChrootNameField(name, "chroot name")
		if e != nil {
			return cfg, e
		}
		cfg, e = cfg.ForChroot(safe, config.DetectRuntime())
		if e != nil {
			return cfg, e
		}
	}
	if username != "" {
		u, e := validation.Username(username)
		if e != nil {
			return cfg, e
		}
		cfg.Username = u
	}
	return cfg, nil
}
func (c *Container) RuntimeFor(name, username string) (Runtime, error) {
	cfg, e := c.ConfigFor(name, username)
	if e != nil {
		return Runtime{}, e
	}
	runner := &sys.Runner{Logger: c.Logger, DryRun: c.DryRun}
	ctrl := controller.New(cfg, runner, c.Logger)
	usr := &users.Manager{Config: cfg, Runner: runner, Registry: c.Registry}
	return Runtime{Config: cfg, Runner: runner, Controller: ctrl, Users: usr}, nil
}
func (c *Container) System() *SystemService         { return &SystemService{C: c} }
func (c *Container) Chroots() *ChrootService        { return &ChrootService{C: c} }
func (c *Container) Users(name string) *UserService { return &UserService{C: c, Name: name} }
func (c *Container) Catalog(kind, name string) *CatalogService {
	return &CatalogService{C: c, Kind: kind, Name: name}
}
func (c *Container) Audit() *AuditService                 { return &AuditService{C: c} }
func (c *Container) Snapshots() *SnapshotService          { return &SnapshotService{C: c} }
func (c *Container) Install() *InstallService             { return &InstallService{C: c} }
func (c *Container) Transfer() *TransferService           { return &TransferService{C: c} }
func (c *Container) Support() *SupportService             { return &SupportService{C: c} }
func (c *Container) Repair() *RepairService               { return &RepairService{C: c} }
func (c *Container) Doctor() *DoctorService               { return &DoctorService{C: c} }
func (c *Container) Preview() *PreviewService             { return &PreviewService{C: c} }
func (c *Container) Lifecycle() *LifecycleService         { return &LifecycleService{C: c} }
func (c *Container) ModuleRuntime() *ModuleRuntimeService { return &ModuleRuntimeService{C: c} }
func (c *Container) ReleaseReadiness() *ReleaseReadinessService {
	return &ReleaseReadinessService{C: c}
}
func (c *Container) Services() *UnitService             { return &UnitService{C: c} }
func (c *Container) ModuleBuilder() *ModuleBuildService { return &ModuleBuildService{C: c} }
func (c *Container) RecoverOperations(ctx context.Context) ([]string, error) {
	return c.Operations.Recover(ctx)
}
func (c *Container) catalog(kind string, cfg config.ChrootConfig) catalog.Catalog {
	return catalog.Catalog{Kind: kind, Config: &cfg}
}
