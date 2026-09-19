package cli

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sort"
	"strings"
	"time"

	"chrootctl/internal/clipboard"
	"chrootctl/internal/completion"
	"chrootctl/internal/model"
	modulepkg "chrootctl/internal/module"
	"chrootctl/internal/redaction"
	"chrootctl/internal/services"
	sys "chrootctl/internal/system"
)

func strptr(s string) *string {
	if s == "" {
		return nil
	}
	v := s
	return &v
}

func (a *App) Dispatch(ctx context.Context) error {
	cmd := a.Inv.Spec.Command
	switch a.Inv.Spec.Handler {
	case "status":
		return a.status(ctx)
	case "mount_action":
		return a.mountAction(ctx, cmd)
	case "doctor":
		return a.doctor(ctx)
	case "logs":
		return a.logs(ctx)
	case "session":
		return a.start(ctx, cmd == "restart")
	case "exec":
		return a.exec(ctx)
	case "units":
		return a.units(ctx, cmd)
	case "install":
		return a.install(ctx)
	case "upgrade":
		return a.upgrade(ctx)
	case "chroots":
		return a.chroots(ctx)
	case "snapshots":
		return a.snapshots(ctx)
	case "transfer":
		return a.transfer(ctx)
	case "artifacts":
		return a.artifacts(ctx)
	case "events":
		return a.events(ctx)
	case "support":
		return a.support(ctx)
	case "clipboard":
		return a.clipboard(ctx)
	case "users":
		return a.users(ctx)
	case "catalog":
		return a.catalog(ctx)
	case "complete":
		return a.complete(ctx)
	case "magisk":
		return a.magisk(ctx)
	case "completion":
		return errors.New("completion shell is required")
	case "version", "wrapper", "app":
		return fmt.Errorf("internal special handler reached service dispatch: %s", a.Inv.Spec.Handler)
	default:
		return fmt.Errorf("unsupported handler %q for command %s", a.Inv.Spec.Handler, cmd)
	}
}

func (a *App) resolveTarget(ctx context.Context, installedOnly bool) (string, error) {
	rows, e := a.Services.Registry.List(ctx)
	if e != nil {
		return "", e
	}
	requested := a.Inv.Globals.Name
	if requested != "" {
		for _, r := range rows {
			if r.Name == requested {
				if installedOnly && !r.Installed {
					return "", fmt.Errorf("chroot is not installed: %s", requested)
				}
				return requested, nil
			}
		}
		return "", fmt.Errorf("unknown chroot: %s", requested)
	}
	names := []string{}
	for _, r := range rows {
		if !installedOnly || r.Installed {
			names = append(names, r.Name)
		}
	}
	sort.Strings(names)
	if len(names) == 1 {
		return names[0], nil
	}
	if len(names) == 0 {
		return "", errors.New("no chroots available for selection")
	}
	return "", fmt.Errorf("chroot selection required; pass --name (%s)", strings.Join(names, ", "))
}
func (a *App) resolveUser(ctx context.Context, target, requested string, nonRoot bool) (string, error) {
	rows, e := a.Services.Users(target).List(ctx)
	if e != nil {
		return "", e
	}
	if requested != "" {
		for _, r := range rows {
			if fmt.Sprint(r["username"]) == requested {
				return requested, nil
			}
		}
		return "", fmt.Errorf("unknown user: %s", requested)
	}
	names := []string{}
	for _, r := range rows {
		n := fmt.Sprint(r["username"])
		if nonRoot && (n == "root" || fmt.Sprint(r["uid"]) == "0") {
			continue
		}
		names = append(names, n)
	}
	sort.Strings(names)
	if len(names) == 1 {
		return names[0], nil
	}
	if len(names) == 0 {
		return "", errors.New("no users available for selection")
	}
	return "", fmt.Errorf("user selection required (%s)", strings.Join(names, ", "))
}

func (a *App) status(ctx context.Context) error {
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	v, e := a.Services.System().Status(ctx, n, a.Inv.Bool("details"))
	if e != nil {
		return e
	}
	for _, row := range v {
		if strings.EqualFold(row.Result, "FAIL") {
			a.ExitCode = 1
			break
		}
	}
	return a.emit("Status", v)
}
func (a *App) doctor(ctx context.Context) error {
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	v, e := a.Services.System().Doctor(ctx, n)
	if e != nil {
		return e
	}
	for _, row := range v {
		if strings.EqualFold(row.Result, "FAIL") {
			a.ExitCode = 1
			break
		}
	}
	return a.emit("Doctor", v)
}
func (a *App) mountAction(ctx context.Context, action string) error {
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	rt, e := a.Services.RuntimeFor(n, "")
	if e != nil {
		return e
	}
	var v model.OperationResult
	switch action {
	case "mount":
		v = rt.Controller.Mount(ctx)
	case "unmount":
		v = rt.Controller.Unmount(ctx)
	case "fix-tty":
		v = rt.Controller.FixTTY(ctx)
	}
	if v.Failed > 0 {
		return fmt.Errorf("%s failed: %s", action, strings.Join(v.Errors, "; "))
	}
	return a.emit(strings.Title(action), v)
}
func (a *App) logs(ctx context.Context) error {
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	tail := a.Inv.Int("tail", 100)
	if a.Inv.String("tail") == "" && a.Inv.Values["tail"] == nil {
		tail = 100
	}
	v, e := a.Services.System().Logs(ctx, n, tail, a.Inv.Bool("all"), a.Inv.String("level"), a.Inv.Bool("follow"))
	if e != nil {
		return e
	}
	if a.Inv.Globals.JSON {
		return a.emit("", v)
	}
	for _, entry := range v.Entries {
		if _, err := fmt.Fprintln(a.Stdout, entry.Line); err != nil {
			return err
		}
	}
	if !a.Inv.Bool("follow") {
		return nil
	}
	cfg, e := a.Services.ConfigFor(n, "")
	if e != nil {
		return e
	}
	return followFile(ctx, cfg.LogFile, a.Stdout, a.Inv.String("level"))
}
func cliLogSeverity(level string) int {
	switch strings.ToUpper(strings.TrimSpace(level)) {
	case "DEBUG":
		return 10
	case "":
		return 0
	case "INFO":
		return 20
	case "WARNING", "WARN":
		return 30
	case "ERROR":
		return 40
	case "CRITICAL":
		return 50
	default:
		return 20
	}
}

func cliLogLineSeverity(line string) int {
	upper := strings.ToUpper(line)
	for _, level := range []string{"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"} {
		if strings.Contains(upper, " "+level+" ") || strings.Contains(upper, "	"+level+"	") {
			return cliLogSeverity(level)
		}
	}
	return cliLogSeverity("INFO")
}

func followFile(ctx context.Context, path string, w io.Writer, level string) error {
	f, e := os.Open(path)
	if e != nil {
		return e
	}
	defer f.Close()
	_, _ = f.Seek(0, io.SeekEnd)
	r := bufio.NewReader(f)
	for {
		line, e := r.ReadString('\n')
		if line != "" {
			clean := redaction.String(line)
			if cliLogLineSeverity(clean) >= cliLogSeverity(level) {
				if _, writeErr := fmt.Fprint(w, clean); writeErr != nil {
					return writeErr
				}
			}
		}
		if e == nil {
			continue
		}
		if e != io.EOF {
			return e
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(200 * time.Millisecond):
		}
	}
}

func (a *App) start(ctx context.Context, restart bool) error {
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	rt, e := a.Services.RuntimeFor(n, "")
	if e != nil {
		return e
	}
	if restart {
		u := rt.Controller.Unmount(ctx)
		if u.Failed > 0 {
			return fmt.Errorf("restart unmount failed: %s", strings.Join(u.Errors, "; "))
		}
	}
	x11 := a.Inv.Bool("x11")
	if e = rt.Controller.Prepare(ctx, x11); e != nil {
		return e
	}
	rootLogin := a.Inv.Bool("root_login") || !a.Inv.Bool("login")
	argv, env, e := rt.Controller.LoginInvocation(rootLogin, x11, rt.Config.Username)
	if e != nil {
		return e
	}
	res, e := rt.Runner.RunAttached(ctx, argv, sys.RunOptions{Env: env, ChrootEnv: true, AllowFailure: true})
	if e != nil {
		return e
	}
	a.ExitCode = res.ReturnCode
	return nil
}
func (a *App) exec(ctx context.Context) error {
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	rt, e := a.Services.RuntimeFor(n, "")
	if e != nil {
		return e
	}
	argv := a.Inv.Strings("argv")
	if len(argv) > 0 && argv[0] == "--" {
		argv = argv[1:]
	}
	chargv, env, e := rt.Controller.ExecInvocation(a.Inv.Bool("root"), argv, a.Inv.String("exec_text"), a.Inv.Bool("x11"), "")
	if e != nil {
		return e
	}
	if e = rt.Controller.Prepare(ctx, a.Inv.Bool("x11")); e != nil {
		return e
	}
	res, e := rt.Runner.RunAttached(ctx, chargv, sys.RunOptions{Env: env, ChrootEnv: true, AllowFailure: true})
	if e != nil {
		return e
	}
	a.ExitCode = res.ReturnCode
	return nil
}

func serviceAddress(values []string, globalName string) (service, chroot string, err error) {
	if globalName != "" {
		if len(values) != 1 {
			return "", "", errors.New("with --name, exactly one SERVICE positional is required")
		}
		return values[0], globalName, nil
	}
	switch len(values) {
	case 1:
		return values[0], "", nil
	case 2:
		return values[1], values[0], nil
	default:
		return "", "", errors.New("service target must be SERVICE or CHROOT SERVICE")
	}
}

func (a *App) units(ctx context.Context, cmd string) error {
	svc := a.Services.Services()
	target := a.Inv.Globals.Name
	if cmd == "run" && a.Inv.Bool("run_list") {
		v, e := svc.List(ctx)
		if e != nil {
			return e
		}
		return a.emit("Services", v)
	}
	names := a.Inv.Strings("run_targets")
	if cmd != "run" {
		names = a.Inv.Strings("service_targets")
	}
	if cmd == "run" && a.Inv.Bool("boot") {
		result, e := svc.Boot(ctx, a.Inv.String("target"), !a.Inv.Bool("no_parallel"))
		if e != nil {
			return &PartialResultError{Err: e, Partial: result, ExitCode: 1}
		}
		return a.emit("Services", result)
	}
	if len(names) == 0 {
		return errors.New("service target is required")
	}
	name, boundTarget, e := serviceAddress(names, target)
	if e != nil {
		return e
	}
	var v any
	switch cmd {
	case "enable":
		v, e = svc.Enable(ctx, name, boundTarget, a.Inv.String("target"))
	case "disable":
		v, e = svc.Disable(ctx, name, boundTarget, a.Inv.String("target"))
	case "journal":
		v, e = svc.Logs(ctx, name, boundTarget, a.Inv.Int("tail", 100))
	case "run":
		switch {
		case a.Inv.Bool("run_status"):
			v, e = svc.Status(ctx, name, boundTarget)
		case a.Inv.Bool("stop"):
			v, e = svc.Stop(ctx, name, boundTarget)
		case a.Inv.Bool("restart"):
			v, e = svc.Restart(ctx, name, boundTarget)
		case a.Inv.Bool("logs"):
			v, e = svc.Logs(ctx, name, boundTarget, a.Inv.Int("tail", 100))
		default:
			v, e = svc.Start(ctx, name, boundTarget, a.Inv.Bool("foreground"))
		}
	}
	if e != nil {
		return &PartialResultError{Err: e, Partial: v, ExitCode: 1}
	}
	if err := a.emit("Services", []any{v}); err != nil {
		return err
	}
	if (cmd == "journal" || (cmd == "run" && a.Inv.Bool("logs"))) && a.Inv.Bool("follow") {
		if row, ok := v.(map[string]any); ok {
			if logPath, ok := row["log_file"].(string); ok && logPath != "" {
				return followFile(ctx, logPath, a.Stdout, "")
			}
		}
	}
	return nil
}

func (a *App) install(ctx context.Context) error {
	distro := a.Inv.String("distro")
	if a.Inv.Bool("wizard") {
		if a.Inv.Globals.NonInteractive {
			return errors.New("install wizard requires an interactive terminal")
		}
		var e error
		distro, e = a.promptChoice("Distro", []string{"ubuntu", "arch"}, distro)
		if e != nil {
			return e
		}
	}
	if distro == "" {
		return errors.New("install requires a target distro (ubuntu or arch)")
	}
	name := a.Inv.Globals.Name
	if name == "" {
		name = distro
	}
	username := a.Inv.String("username")
	if username == "" {
		username = a.Services.BaseConfig.Username
	}
	arch := a.Inv.String("arch")
	if arch == "" {
		arch = a.Services.BaseConfig.TargetArch
	}
	if a.Inv.Bool("list_versions") {
		v, e := a.Services.Install().ListVersions(ctx, distro, name, username)
		if e != nil {
			return e
		}
		return a.emit("Available Versions", v)
	}
	req := model.InstallRequest{Distro: distro, Name: name, Username: username, Arch: arch, Preset: strptr(a.Inv.String("preset")), Profile: strptr(a.Inv.String("profile")), Desktop: strptr(a.Inv.String("desktop")), Release: strptr(a.Inv.String("release")), Version: strptr(a.Inv.String("version")), Mirror: strptr(a.Inv.String("mirror")), Phase: strptr(a.Inv.String("phase")), ForcePhase: a.Inv.Bool("force_phase"), Resume: a.Inv.Bool("resume"), Repair: a.Inv.Bool("repair"), OverwriteExisting: a.Inv.Bool("overwrite_existing"), Tools: a.Inv.Strings("tools"), Addons: a.Inv.Strings("addons")}
	if a.Inv.Bool("select_tools") || a.Inv.Bool("select_addons") {
		return errors.New("interactive catalog multi-selection is not available in the native CLI; pass repeated --tool/--addon")
	}
	v, e := a.Services.Install().Install(ctx, req, a.progress)
	if e != nil {
		if v.ChrootName != "" || len(v.Phases) > 0 || len(v.ToolResults) > 0 || len(v.AddonResults) > 0 {
			return &PartialResultError{Err: e, Partial: v, ExitCode: 1}
		}
		return e
	}
	return a.emit("Install Results", v)
}
func (a *App) promptChoice(label string, choices []string, current string) (string, error) {
	if current != "" {
		return current, nil
	}
	fmt.Fprintf(a.Stderr, "%s (%s): ", label, strings.Join(choices, "/"))
	line, e := bufio.NewReader(a.Stdin).ReadString('\n')
	if e != nil && e != io.EOF {
		return "", e
	}
	v := strings.TrimSpace(line)
	for _, x := range choices {
		if v == x {
			return v, nil
		}
	}
	return "", fmt.Errorf("invalid %s: %s", strings.ToLower(label), v)
}
func (a *App) upgrade(ctx context.Context) error {
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	u := a.Inv.String("username")
	if u == "" {
		u, e = a.resolveUser(ctx, n, "", true)
		if e != nil {
			return e
		}
	}
	v, e := a.Services.Install().Upgrade(ctx, n, u, a.progress)
	if e != nil {
		return e
	}
	return a.emit("Upgrade", v)
}

func (a *App) chroots(ctx context.Context) error {
	switch a.Inv.Spec.Command {
	case "chroots":
		return errors.New("chroots subcommand is required")
	case "chroots list":
		v, e := a.Services.Chroots().List(ctx)
		if e != nil {
			return e
		}
		return a.emit("Known Chroots", v)
	case "chroots show":
		n, e := a.resolveTarget(ctx, false)
		if e != nil {
			return e
		}
		v, e := a.Services.Chroots().Get(ctx, n)
		if e != nil {
			return e
		}
		return a.emit("Chroot Details", v)
	case "chroots remove":
		n, e := a.resolveTarget(ctx, false)
		if e != nil {
			return e
		}
		if e = a.confirm("Remove chroot '"+n+"'?", a.Inv.Bool("yes")); e != nil {
			return e
		}
		v, e := a.Services.Chroots().Remove(ctx, n)
		if e != nil {
			return e
		}
		return a.emit("Chroot Remove", v)
	case "chroots rename":
		n, e := a.resolveTarget(ctx, false)
		if e != nil {
			return e
		}
		nn := a.Inv.String("new_name")
		if nn == "" {
			return errors.New("new chroot name is required")
		}
		v, e := a.Services.Chroots().Rename(ctx, n, nn)
		if e != nil {
			return e
		}
		return a.emit("Chroot Rename", v)
	case "chroots export":
		n, e := a.resolveTarget(ctx, false)
		if e != nil {
			return e
		}
		arc := a.Inv.String("archive")
		if arc == "" {
			arc = services.ManagedArchive(n, "tar.zst")
		}
		v, e := a.Services.Transfer().ExportWithControl(ctx, n, arc, a.Inv.String("password"), services.TransferControl{Progress: a.progress})
		if e != nil {
			return e
		}
		return a.emit("Chroot Export", v)
	case "chroots import":
		v, e := a.Services.Transfer().ImportWithControl(ctx, a.Inv.String("archive"), a.Inv.String("import_name"), a.Inv.String("conflict"), a.Inv.String("password"), a.Inv.String("post_import"), services.TransferControl{Progress: a.progress, AllowLegacyMetadata: a.Inv.Bool("allow_legacy_metadata")})
		if e != nil {
			return e
		}
		return a.emit("Chroot Import", v)
	case "chroots diff":
		v, e := a.Services.Chroots().PackageDiff(ctx, a.Inv.String("left_name"), a.Inv.String("right_name"))
		if e != nil {
			return e
		}
		return a.emit("Chroot Package Diff", v)
	case "chroots validate-import":
		n := a.Inv.String("validate_name")
		if n == "" {
			var e error
			n, e = a.resolveTarget(ctx, false)
			if e != nil {
				return e
			}
		}
		v, e := a.Services.Chroots().ValidateImport(ctx, n)
		if e != nil {
			return e
		}
		if ok, _ := v["validation_ok"].(bool); !ok {
			a.ExitCode = 1
		}
		return a.emit("Imported Chroot Validation", v)
	}
	return errors.New("unsupported chroots command")
}
func (a *App) snapshots(ctx context.Context) error {
	switch a.Inv.Spec.Command {
	case "snapshots":
		return errors.New("snapshots subcommand is required")
	case "snapshots list":
		n, err := a.resolveTarget(ctx, false)
		if err != nil {
			return err
		}
		rows, err := a.Services.Snapshots().List(ctx, n, a.Inv.Int("limit", 100))
		if err != nil {
			return err
		}
		return a.emit("Managed Snapshots", rows)
	case "snapshots create":
		n, err := a.resolveTarget(ctx, false)
		if err != nil {
			return err
		}
		result, err := a.Services.Snapshots().Create(ctx, n, a.Inv.String("snapshot"), a.Inv.String("note"))
		if err != nil {
			return err
		}
		return a.emit("Snapshot Create", result)
	case "snapshots restore":
		n, err := a.resolveTarget(ctx, false)
		if err != nil {
			return err
		}
		snapshot := a.Inv.String("snapshot")
		if err = a.confirm("Restore snapshot '"+snapshot+"' over chroot '"+n+"'?", a.Inv.Bool("yes")); err != nil {
			return err
		}
		result, err := a.Services.Snapshots().Restore(ctx, n, snapshot)
		if err != nil {
			return err
		}
		return a.emit("Snapshot Restore", result)
	case "snapshots export":
		n, err := a.resolveTarget(ctx, false)
		if err != nil {
			return err
		}
		result, err := a.Services.Snapshots().Export(ctx, n, a.Inv.String("snapshot"), a.Inv.String("archive"))
		if err != nil {
			return err
		}
		return a.emit("Snapshot Export", result)
	default:
		return errors.New("unsupported snapshots command")
	}
}

func (a *App) transfer(ctx context.Context) error {
	switch a.Inv.Spec.Command {
	case "transfer":
		return errors.New("transfer subcommand is required")
	case "transfer export":
		n, e := a.resolveTarget(ctx, false)
		if e != nil {
			return e
		}
		arc := a.Inv.String("archive")
		if arc == "" {
			arc = services.ManagedArchive(n, "tar.zst")
		}
		v, e := a.Services.Transfer().ExportWithControl(ctx, n, arc, a.Inv.String("password"), services.TransferControl{Progress: a.progress})
		if e != nil {
			return e
		}
		return a.emit("Transfer Export", v)
	case "transfer inspect":
		v, e := a.Services.Transfer().InspectWithControl(ctx, a.Inv.String("archive"), a.Inv.String("password"), services.TransferControl{Progress: a.progress, AllowLegacyMetadata: a.Inv.Bool("allow_legacy_metadata")})
		if e != nil {
			return e
		}
		return a.emit("Transfer Inspect", v)
	case "transfer import":
		v, e := a.Services.Transfer().ImportWithControl(ctx, a.Inv.String("archive"), a.Inv.String("import_name"), a.Inv.String("conflict"), a.Inv.String("password"), a.Inv.String("post_import"), services.TransferControl{Progress: a.progress, AllowLegacyMetadata: a.Inv.Bool("allow_legacy_metadata")})
		if e != nil {
			return e
		}
		return a.emit("Transfer Import", v)
	}
	return errors.New("unsupported transfer command")
}
func (a *App) artifacts(ctx context.Context) error {
	switch a.Inv.Spec.Command {
	case "artifacts":
		return errors.New("artifacts subcommand is required")
	case "artifacts list":
		v, e := a.Services.Transfer().TempState(ctx)
		if e != nil {
			return e
		}
		return a.emit("Managed Artifacts", v)
	case "artifacts root":
		return a.emit("Managed Artifact Root", a.Services.Transfer().ArtifactRoot())
	case "artifacts cleanup":
		id := a.Inv.String("artifact_id")
		path := a.Inv.String("path")
		all := a.Inv.Bool("all") || a.Inv.Bool("delete_all")
		if !all && id == "" && path == "" {
			return errors.New("artifacts cleanup requires --all, --artifact-id, or --path")
		}
		label := "Clean managed artifact(s)?"
		if all {
			label = "Clean all managed transfer artifacts?"
		} else if id != "" {
			label = "Clean managed artifact '" + id + "'?"
		} else if path != "" {
			label = "Clean managed artifact at '" + path + "'?"
		}
		if e := a.confirm(label, a.Inv.Bool("yes")); e != nil {
			return e
		}
		v, e := a.Services.Transfer().DeleteTemp(ctx, id, path, all)
		if e != nil {
			return e
		}
		return a.emit("Managed Artifact Cleanup", v)
	}
	return errors.New("unsupported artifacts command")
}

func (a *App) events(ctx context.Context) error {
	if a.Inv.Spec.Command != "events list" {
		return errors.New("events subcommand is required")
	}
	v, e := a.Services.Audit().Recent(ctx, a.Inv.Int("limit", 20))
	if e != nil {
		return e
	}
	return a.emit("Audit Events", v)
}
func (a *App) support(ctx context.Context) error {
	v, e := a.Services.Support().ExportBundle(ctx, a.Inv.String("archive"), nil)
	if e != nil {
		return e
	}
	return a.emit("Support Bundle", v)
}

func (a *App) clipboard(ctx context.Context) error {
	cfg := a.Services.BaseConfig
	paths := clipboard.DefaultPaths(cfg)
	if x := a.Inv.String("socket"); x != "" {
		paths.SocketPath = x
	}
	if x := a.Inv.String("pid_file"); x != "" {
		paths.PIDFile = x
	}
	if x := a.Inv.String("log_file"); x != "" {
		paths.LogFile = x
	}
	runner := &sys.Runner{Logger: a.Services.Logger, DryRun: a.Services.DryRun}
	switch a.Inv.Spec.Command {
	case "clipboard", "clipboard daemon":
		return errors.New("clipboard subcommand is required")
	case "clipboard daemon start":
		if a.Services.DryRun {
			return a.emit("", map[string]any{"dryRun": true, "action": "clipboard.daemon.start", "socket": paths.SocketPath})
		}
		v, e := clipboard.StartDaemon(ctx, cfg, runner, paths)
		if e != nil {
			return e
		}
		return a.emit("", v)
	case "clipboard daemon stop":
		if a.Services.DryRun {
			return a.emit("", map[string]any{"dryRun": true, "action": "clipboard.daemon.stop", "pidFile": paths.PIDFile, "socket": paths.SocketPath})
		}
		return a.emit("", clipboard.StopDaemon(paths))
	case "clipboard daemon status":
		v := clipboard.DaemonStatus(paths.PIDFile)
		v["socket"] = paths.SocketPath
		v["pid_file"] = paths.PIDFile
		v["log_file"] = paths.LogFile
		return a.emit("", v)
	case "clipboard daemon run":
		if a.Services.DryRun {
			return a.emit("", map[string]any{"dryRun": true, "action": "clipboard.daemon.run", "socket": paths.SocketPath})
		}
		return clipboard.RunDaemon(ctx, cfg, runner, paths)
	case "clipboard doctor":
		if a.Inv.Globals.Name != "" {
			var e error
			cfg, e = a.Services.ConfigFor(a.Inv.Globals.Name, "")
			if e != nil {
				return e
			}
		}
		return a.emit("", clipboard.Doctor(cfg, paths))
	case "clipboard set":
		text, e := clipboardSetText(a.Inv, a.Stdin)
		if e != nil {
			return e
		}
		socket := a.Inv.String("socket")
		if socket == "" {
			socket = paths.SocketPath
		}
		if a.Services.DryRun {
			return a.emit("", map[string]any{"dryRun": true, "action": "clipboard.set", "socket": socket, "bytes": len([]byte(text))})
		}
		v, e := clipboard.SocketSet(ctx, socket, text)
		if e != nil {
			return e
		}
		if !v.OK {
			return errors.New(v.Error)
		}
		return nil
	case "clipboard get":
		socket := a.Inv.String("socket")
		if socket == "" {
			socket = paths.SocketPath
		}
		v, e := clipboard.SocketGet(ctx, socket)
		if e != nil {
			return e
		}
		if !v.OK {
			return errors.New(v.Error)
		}
		_, e = fmt.Fprint(a.Stdout, v.Text)
		return e
	}
	return errors.New("unsupported clipboard command")
}

func clipboardSetText(inv Invocation, stdin io.Reader) (string, error) {
	if values := inv.Strings("text"); len(values) > 0 {
		return strings.Join(values, " "), nil
	}
	limited := &io.LimitedReader{R: stdin, N: clipboard.MaxClipboardTextBytes + 1}
	b, err := io.ReadAll(limited)
	if err != nil {
		return "", err
	}
	if len(b) > clipboard.MaxClipboardTextBytes {
		return "", fmt.Errorf("clipboard stdin exceeds 1 MiB")
	}
	return string(b), nil
}

func (a *App) users(ctx context.Context) error {
	if a.Inv.Spec.Command == "users" {
		return errors.New("users subcommand is required")
	}
	n, e := a.resolveTarget(ctx, true)
	if e != nil {
		return e
	}
	svc := a.Services.Users(n)
	requested := a.Inv.String("username")
	switch a.Inv.Spec.Command {
	case "users list":
		v, e := svc.List(ctx)
		if e != nil {
			return e
		}
		return a.emit("Chroot Users", v)
	case "users add":
		if requested == "" {
			return errors.New("username is required")
		}
		v, e := svc.Add(ctx, requested, a.Inv.String("shell"), a.Inv.Bool("sudo"))
		if e != nil {
			return e
		}
		return a.emit("Chroot User Add", v)
	case "users show", "users remove", "users password", "users shell", "users sudo", "users show-id", "users sync-id":
		if requested == "" {
			requested, e = a.resolveUser(ctx, n, "", a.Inv.Spec.Command == "users show-id" || a.Inv.Spec.Command == "users sync-id")
			if e != nil {
				return e
			}
		}
	}
	switch a.Inv.Spec.Command {
	case "users show":
		v, e := svc.Show(ctx, requested)
		if e != nil {
			return e
		}
		return a.emit("Chroot User", v)
	case "users remove":
		if e = a.confirm("Remove user '"+requested+"'?", a.Inv.Bool("yes")); e != nil {
			return e
		}
		v, e := svc.Remove(ctx, requested, a.Inv.Bool("delete_home"))
		if e != nil {
			return e
		}
		return a.emit("Chroot User Remove", v)
	case "users password":
		password, e := a.readPassword()
		if e != nil {
			return e
		}
		v, e := svc.SetPassword(ctx, requested, password)
		if e != nil {
			return e
		}
		return a.emit("Chroot User Password", v)
	case "users shell":
		v, e := svc.SetShell(ctx, requested, a.Inv.String("shell"))
		if e != nil {
			return e
		}
		return a.emit("Chroot User Shell", v)
	case "users sudo":
		if a.Inv.Bool("enable") == a.Inv.Bool("disable") {
			return errors.New("choose exactly one of --enable or --disable")
		}
		v, e := svc.SetSudo(ctx, requested, a.Inv.Bool("enable"))
		if e != nil {
			return e
		}
		return a.emit("Chroot User Sudo", v)
	case "users show-id":
		v, e := svc.ShowID(ctx, requested)
		if e != nil {
			return e
		}
		return a.emit("User IDs", v)
	case "users sync-id":
		v, e := svc.SyncID(ctx, requested, !a.Inv.Bool("no_fix_ownership"))
		if e != nil {
			return e
		}
		return a.emit("User Sync", v)
	}
	return errors.New("unsupported users command")
}

func (a *App) catalog(ctx context.Context) error {
	cmd := a.Inv.Spec.Command
	kind := "tool"
	group := "tools"
	if strings.HasPrefix(cmd, "addons") {
		kind = "addon"
		group = "addons"
	}
	if cmd == group {
		return fmt.Errorf("%s subcommand is required", group)
	}
	target := a.Inv.Globals.Name
	svc := a.Services.Catalog(kind, target)
	distro := a.Inv.String("distro")
	category := a.Inv.String("category")
	switch cmd {
	case group + " categories":
		v, e := svc.Categories(distro)
		if e != nil {
			return e
		}
		return a.emit(strings.Title(group)+" Categories", v)
	case group + " list":
		v, e := svc.ListEntries(distro, category)
		if e != nil {
			return e
		}
		return a.emit(strings.Title(group), v)
	case group + " show":
		name := a.Inv.String(kind + "_name")
		if name == "" {
			v, e := svc.ListEntries(distro, category)
			if e != nil {
				return e
			}
			if len(v) != 1 {
				return errors.New(kind + " selection required")
			}
			name = v[0].Name
		}
		v, e := svc.GetEntry(name)
		if e != nil {
			return e
		}
		return a.emit(strings.Title(kind), v)
	case group + " apply":
		n, e := a.resolveTarget(ctx, true)
		if e != nil {
			return e
		}
		svc = a.Services.Catalog(kind, n)
		names := a.Inv.Strings(kind + "_names")
		if len(names) == 0 {
			entries, e := svc.ListEntries("", category)
			if e != nil {
				return e
			}
			if len(entries) == 1 {
				names = []string{entries[0].Name}
			} else {
				return errors.New(kind + " name is required")
			}
		}
		v, e := svc.Apply(ctx, names, a.progress)
		if e != nil {
			return &PartialResultError{Err: e, Partial: v, ExitCode: 1}
		}
		return a.emit(strings.Title(group)+" Apply", v)
	}
	return errors.New("unsupported catalog command")
}

func (a *App) complete(ctx context.Context) error {
	topic := a.Inv.String("topic")
	vals := a.Inv.Strings("values")
	switch topic {
	case "chroots", "installed-chroots", "chroot-details":
		rows, e := a.Services.Registry.List(ctx)
		if e != nil {
			return e
		}
		if topic == "chroot-details" {
			_, e = fmt.Fprint(a.Stdout, completion.ChrootDetails(rows))
			return e
		}
		_, e = fmt.Fprint(a.Stdout, completion.ChrootNames(rows, topic == "installed-chroots"))
		return e
	case "chroot-preview":
		if len(vals) == 0 {
			return nil
		}
		r, e := a.Services.Registry.Get(ctx, vals[0])
		if e != nil || r == nil {
			return e
		}
		_, e = fmt.Fprintf(a.Stdout, "name: %s\ndistro: %s\nphase: %s\npath: %s\ninstalled: %v\n", r.Name, r.Distro, r.Phase, r.Path, r.Installed)
		return e
	case "users":
		n := a.Inv.Globals.Name
		if n == "" && len(vals) > 0 {
			n = vals[0]
		}
		if n == "" {
			var e error
			n, e = a.resolveTarget(ctx, true)
			if e != nil {
				return nil
			}
		}
		rows, e := a.Services.Users(n).List(ctx)
		if e != nil {
			return e
		}
		names := []string{}
		for _, r := range rows {
			names = append(names, fmt.Sprint(r["username"]))
		}
		sort.Strings(names)
		_, e = fmt.Fprint(a.Stdout, strings.Join(names, "\n"))
		return e
	case "tools", "addons", "tool-categories", "addon-categories", "tool-details", "addon-details", "tool-preview", "addon-preview":
		return a.completeCatalog(topic, vals)
	}
	return nil
}
func (a *App) completeCatalog(topic string, vals []string) error {
	kind := "tool"
	if strings.Contains(topic, "addon") {
		kind = "addon"
	}
	svc := a.Services.Catalog(kind, "")
	distro := ""
	category := ""
	if len(vals) > 0 {
		distro = vals[0]
	}
	if len(vals) > 1 {
		category = vals[1]
	}
	if strings.Contains(topic, "categories") {
		v, e := svc.Categories(distro)
		if e != nil {
			return e
		}
		_, e = fmt.Fprint(a.Stdout, strings.Join(v, "\n"))
		return e
	}
	if strings.Contains(topic, "preview") {
		if len(vals) == 0 {
			return nil
		}
		v, e := svc.GetEntry(vals[0])
		if e != nil {
			return e
		}
		_, e = fmt.Fprintf(a.Stdout, "name: %s\nkind: %s\ndistros: %s\ncategories: %s\nscript: %s\nstate: %s\nrisk: %s\nrollback: %s\nsource: %s\nscript_sha256: %s\n\n%s", v.Name, v.Kind, strings.Join(v.Distros, ","), strings.Join(v.Categories, ","), v.Script, v.State, v.RiskLevel, v.Rollback, v.Source, v.ScriptSHA256, v.Description)
		return e
	}
	v, e := svc.ListEntries(distro, category)
	if e != nil {
		return e
	}
	lines := []string{}
	for _, x := range v {
		if strings.Contains(topic, "details") {
			cat := strings.Join(x.Categories, ",")
			if cat == "" {
				cat = "uncategorized"
			}
			lines = append(lines, strings.Join([]string{x.Name, cat, strings.Join(x.Distros, ","), x.State, x.RiskLevel, x.Description}, "\t"))
		} else {
			lines = append(lines, x.Name)
		}
	}
	_, e = fmt.Fprint(a.Stdout, strings.Join(lines, "\n"))
	return e
}

func (a *App) confirm(prompt string, yes bool) error {
	if yes {
		return nil
	}
	if a.Inv.Globals.NonInteractive {
		return errors.New(prompt + " confirmation required in non-interactive mode")
	}
	fmt.Fprint(a.Stderr, prompt+" [y/N] ")
	line, e := bufio.NewReader(a.Stdin).ReadString('\n')
	if e != nil && e != io.EOF {
		return e
	}
	v := strings.ToLower(strings.TrimSpace(line))
	if v != "y" && v != "yes" {
		return errors.New("cancelled")
	}
	return nil
}
func (a *App) readPassword() (password string, err error) {
	if a.Inv.Globals.NonInteractive {
		return "", errors.New("password prompt is unavailable in non-interactive mode")
	}
	tty, ok := a.Stdin.(*os.File)
	echoDisabled := false
	if ok {
		cmd := exec.Command("stty", "-echo")
		cmd.Stdin = tty
		cmd.Stdout = a.Stderr
		cmd.Stderr = a.Stderr
		if e := cmd.Run(); e != nil {
			return "", fmt.Errorf("disable terminal echo: %w", e)
		}
		echoDisabled = true
		defer func() {
			c := exec.Command("stty", "echo")
			c.Stdin = tty
			c.Stdout = a.Stderr
			c.Stderr = a.Stderr
			if e := c.Run(); err == nil && e != nil {
				err = fmt.Errorf("restore terminal echo: %w", e)
			}
			fmt.Fprintln(a.Stderr)
		}()
	}
	reader := bufio.NewReader(a.Stdin)
	fmt.Fprint(a.Stderr, "Password: ")
	line, e := reader.ReadString('\n')
	if e != nil && e != io.EOF {
		return "", e
	}
	v := strings.TrimRight(line, "\r\n")
	if v == "" {
		return "", errors.New("password must not be empty")
	}
	fmt.Fprint(a.Stderr, "Confirm password: ")
	confirmLine, e := reader.ReadString('\n')
	if e != nil && e != io.EOF {
		return "", e
	}
	confirm := strings.TrimRight(confirmLine, "\r\n")
	if confirm != v {
		return "", errors.New("password confirmation does not match")
	}
	_ = echoDisabled
	return v, nil
}

func (a *App) magisk(ctx context.Context) error {
	if a.Inv.Spec.Command == "magisk" {
		return errors.New("magisk subcommand is required")
	}
	if a.Inv.Spec.Command != "magisk render" {
		return errors.New("unsupported magisk command")
	}
	requested := a.Inv.Strings("magisk_names")
	targets, err := a.Services.ModuleBuilder().ResolveStartupTargets(ctx, services.ModuleBuildRequest{
		StartupTargets: requested,
		AllInstalled:   len(requested) == 0 && a.Inv.Bool("all_installed"),
	})
	if err != nil {
		return err
	}
	opts := modulepkg.Options{OutputDir: a.Inv.String("output"), ZipPath: a.Inv.String("zip_path"), NativeRuntimeDir: a.Inv.String("native_runtime_dir"), StartupTargets: targets}
	if a.Services.DryRun {
		return a.emit("Magisk module", map[string]any{"dryRun": true, "output_dir": opts.OutputDir, "archive_path": opts.ZipPath, "startup_targets": targets})
	}
	if err := modulepkg.Render(opts); err != nil {
		return err
	}
	result := map[string]any{"output_dir": opts.OutputDir, "archive_path": opts.ZipPath, "startup_targets": targets}
	return a.emit("Magisk module", result)
}
