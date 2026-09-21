package services

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"chrootctl/internal/catalog"
	"chrootctl/internal/config"
	"chrootctl/internal/controller"
	"chrootctl/internal/logging"
	"chrootctl/internal/mutation"
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

type ResolvedTarget struct {
	Record   registry.Chroot
	Config   config.ChrootConfig
	RootPath string
}

type Container struct {
	BaseConfig config.ChrootConfig
	ConfigPath string
	Registry   *registry.Registry
	Logger     *logging.Logger
	Operations *operations.Manager
	Mutations  *mutation.Engine
	DryRun     bool
}

func New(configPath string, dryRun, verbose bool) (*Container, error) {
	effectiveConfigPath := configPath
	if effectiveConfigPath == "" {
		effectiveConfigPath = config.DefaultConfigPath(config.DetectRuntime())
	}
	load := config.Load
	if dryRun {
		load = config.LoadReadOnly
	}
	cfg, err := load(configPath, config.WithChrootCounter(registry.CountChroots))
	if err != nil {
		return nil, err
	}
	var reg *registry.Registry
	if dryRun {
		if _, statErr := os.Stat(cfg.DatabasePath); statErr == nil {
			reg, err = registry.OpenReadOnly(cfg.DatabasePath)
		} else if errors.Is(statErr, os.ErrNotExist) {
			reg, err = registry.OpenEphemeral()
		} else {
			err = statErr
		}
	} else {
		reg, err = registry.Open(cfg.DatabasePath)
	}
	if err != nil {
		return nil, err
	}
	var logger *logging.Logger
	if dryRun {
		logger = logging.ConfigureReadOnly(verbose)
	} else {
		logger = logging.Configure(cfg.LogFile, verbose)
	}
	opRoot := filepath.Join(filepath.Dir(cfg.DatabasePath), "operations")
	var ops *operations.Manager
	if !dryRun {
		ops, err = operations.NewManager(opRoot, false)
		if err != nil {
			reg.Close()
			logger.Close()
			return nil, err
		}
	}
	return &Container{BaseConfig: cfg, ConfigPath: effectiveConfigPath, Registry: reg, Logger: logger, Operations: ops, Mutations: mutation.New(reg, opRoot, dryRun), DryRun: dryRun}, nil
}
func NewWith(cfg config.ChrootConfig, reg *registry.Registry, logger *logging.Logger, dryRun bool) (*Container, error) {
	if reg == nil {
		return nil, fmt.Errorf("services registry is nil")
	}
	opRoot := filepath.Join(filepath.Dir(cfg.DatabasePath), "operations")
	var ops *operations.Manager
	var err error
	if dryRun {
		if err = reg.SetQueryOnly(context.Background(), true); err != nil {
			return nil, err
		}
		if logger == nil {
			logger = logging.ConfigureReadOnly(false)
		}
	} else {
		ops, err = operations.NewManager(opRoot, false)
		if err != nil {
			return nil, err
		}
	}
	return &Container{BaseConfig: cfg, Registry: reg, Logger: logger, Operations: ops, Mutations: mutation.New(reg, opRoot, dryRun), DryRun: dryRun}, nil
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
func (c *Container) ResolveTarget(ctx context.Context, name string, requireInstalled bool) (*ResolvedTarget, error) {
	safe, err := validation.ChrootNameField(name, "chroot name")
	if err != nil {
		return nil, err
	}
	record, err := c.Registry.Get(ctx, safe)
	if err != nil {
		return nil, err
	}
	if record == nil {
		return nil, nil
	}
	if requireInstalled && !record.Installed {
		return nil, fmt.Errorf("chroot %s is not installed", safe)
	}
	root, err := validateRegisteredTargetPath(c.BaseConfig.ChrootRoot, safe, record.Path)
	if err != nil {
		return nil, err
	}
	owner, err := c.Registry.FindByPath(ctx, root)
	if err != nil {
		return nil, err
	}
	if owner == nil || owner.Name != safe {
		return nil, fmt.Errorf("registered chroot path %s does not have unique ownership by %s", root, safe)
	}
	cfg, err := c.ConfigFor(safe, "")
	if err != nil {
		return nil, err
	}
	// Existing records own their filesystem identity. Configuration supplies
	// behavioral defaults, but must not silently relocate a registered target.
	cfg.ChrootRoot = filepath.Dir(root)
	cfg.DistroName = safe
	if record.Arch != nil && *record.Arch != "" {
		cfg.TargetArch = *record.Arch
	}
	return &ResolvedTarget{Record: *record, Config: cfg, RootPath: root}, nil
}

func (c *Container) RuntimeFor(name, username string) (Runtime, error) {
	cfg, e := c.ConfigFor(name, username)
	if e != nil {
		return Runtime{}, e
	}
	if name != "" {
		resolved, err := c.ResolveTarget(context.Background(), name, false)
		if err != nil {
			return Runtime{}, err
		}
		if resolved != nil {
			cfg = resolved.Config
			if username != "" {
				u, err := validation.Username(username)
				if err != nil {
					return Runtime{}, err
				}
				cfg.Username = u
			}
		}
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
func (c *Container) RecoverFilesystemMutations(ctx context.Context, target string) (mutation.RecoveryReport, error) {
	if c.Mutations == nil {
		return mutation.RecoveryReport{}, nil
	}
	return c.Mutations.RecoverLocked(ctx, target)
}
func (c *Container) catalog(kind string, cfg config.ChrootConfig) catalog.Catalog {
	return catalog.Catalog{Kind: kind, Config: &cfg}
}
func (c *Container) Sessions() *SessionService { return &SessionService{C: c} }
