package cli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"syscall"

	"chrootctl/internal/bridge"
	"chrootctl/internal/completion"
	"chrootctl/internal/config"
	"chrootctl/internal/redaction"
	"chrootctl/internal/services"
	sys "chrootctl/internal/system"
	"chrootctl/internal/version"
)

type SignalError struct{ Signal syscall.Signal }

func (e SignalError) Error() string              { return fmt.Sprintf("terminated by signal %d", e.Signal) }
func NewSignalError(signal syscall.Signal) error { return SignalError{Signal: signal} }

func cliMutationScope(inv Invocation) string {
	if inv.Spec.Mutability != "mutate" && inv.Spec.Mutability != "mixed" {
		return "none"
	}
	switch inv.Spec.Command {
	case "install", "chroots import", "transfer import", "support-bundle", "magisk render",
		"clipboard daemon start", "clipboard daemon stop", "clipboard daemon run", "clipboard set":
		return "global"
	case "run":
		if inv.Bool("run_list") || inv.Bool("run_status") || inv.Bool("logs") {
			return "none"
		}
		if inv.Bool("boot") {
			return "global"
		}
		return "global"
	case "enable", "disable":
		return "global"
	default:
		return "target"
	}
}

func mutationTarget(ctx context.Context, app *App, inv Invocation) (string, error) {
	if inv.Spec.Command == "install" || inv.Spec.Command == "chroots import" || inv.Spec.Command == "transfer import" {
		return "", nil
	}
	return app.resolveTarget(ctx, false)
}

func Run(ctx context.Context, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	inv, err := Parse(args)
	if err != nil {
		if requestedJSON(args) {
			_ = emitJSONEnvelope(stdout, bestCommand(args), false, nil, err, false)
		} else {
			_, _ = fmt.Fprintln(stderr, "chrootctl:", redaction.String(err.Error()))
			if spec, ok := HelpSpecForArgs(args); ok {
				_, _ = fmt.Fprint(stderr, Help(spec))
			} else {
				_, _ = fmt.Fprint(stderr, RootHelp())
			}
		}
		return 2
	}
	if inv.Help && inv.Spec.Command == "" {
		if _, e := fmt.Fprint(stdout, RootHelp()); e != nil {
			return 1
		}
		return 0
	}
	if inv.Help {
		if _, e := fmt.Fprint(stdout, Help(inv.Spec)); e != nil {
			return 1
		}
		return 0
	}

	// Version is a first-class contract action and needs no service container.
	if inv.Spec.Command == "version" {
		data := map[string]any{"version": version.Version, "commit": version.Commit, "backend": "go-native"}
		if inv.Globals.JSON {
			if emitJSONEnvelope(stdout, "version", true, data, nil, false) != nil {
				return 1
			}
		} else {
			if _, e := fmt.Fprintf(stdout, "chrootctl %s (Go native backend, commit %s)\n", version.Version, version.Commit); e != nil {
				return 1
			}
		}
		return signalExitCode(ctx, 0)
	}
	if inv.Spec.Command == "completion zsh" {
		text, e := completion.GenerateZsh()
		if e != nil {
			return writeFailure(inv, stdout, stderr, e, nil, 1)
		}
		if _, e = io.WriteString(stdout, text); e != nil {
			return 1
		}
		return signalExitCode(ctx, 0)
	}
	if inv.Spec.Command == "__complete" {
		err := completion.Query(ctx, completion.QueryOptions{
			ConfigPath: inv.Globals.ConfigPath,
			Name:       inv.Globals.Name,
			Topic:      inv.String("topic"),
			Values:     inv.Strings("values"),
		}, stdout)
		if err != nil {
			_, _ = fmt.Fprintln(stderr, "chrootctl completion:", redaction.String(err.Error()))
			return 1
		}
		return 0
	}
	if inv.Spec.Command == "wrapper install" {
		return signalExitCode(ctx, InstallWrapper(inv, stdout, stderr))
	}
	if inv.Spec.Command == "app" {
		bargs := []string{}
		if inv.Globals.ConfigPath != "" {
			bargs = append(bargs, "--config", inv.Globals.ConfigPath)
		}
		if inv.Globals.DryRun {
			bargs = append(bargs, "--dry-run")
		}
		if inv.Globals.Verbose {
			bargs = append(bargs, "--verbose")
		}
		bargs = append(bargs, inv.Strings("bridge_args")...)
		return signalExitCode(ctx, bridge.RunApp(ctx, bargs, stdin, stdout, stderr))
	}

	if shouldReexecPrivilege(inv, sys.IsRoot()) {
		if inv.Globals.NoSudo {
			return writeFailure(inv, stdout, stderr, errors.New("permission error: root privileges required; rerun without --no-sudo to auto-escalate"), nil, 2)
		}
		reexecArgs := privilegeReexecArgs(inv, args)
		argv, e := sys.ReexecArgv(reexecArgs)
		if e != nil {
			return writeFailure(inv, stdout, stderr, e, nil, 1)
		}
		runner := sys.Runner{}
		code, e := runner.ReexecWithRootIO(ctx, argv, stdin, stdout, stderr)
		if e != nil {
			return writeFailure(inv, stdout, stderr, e, nil, 1)
		}
		return signalExitCode(ctx, code)
	}

	s, err := services.New(inv.Globals.ConfigPath, inv.Globals.DryRun, inv.Globals.Verbose)
	if err != nil {
		return writeFailure(inv, stdout, stderr, err, nil, 1)
	}
	defer s.Close()
	app := App{Services: s, Inv: inv, Stdin: stdin, Stdout: stdout, Stderr: stderr}
	scope := cliMutationScope(inv)
	if scope != "none" {
		target := ""
		if scope == "target" {
			target, err = mutationTarget(ctx, &app, inv)
			if err != nil {
				return signalExitCode(ctx, writeFailure(inv, stdout, stderr, err, nil, 1))
			}
		}
		lockedCtx, release, guardErr := s.Mutations.Guard(ctx, scope, target, "cli-"+strings.ReplaceAll(inv.Spec.Command, " ", "-"))
		if guardErr != nil {
			return signalExitCode(ctx, writeFailure(inv, stdout, stderr, guardErr, nil, 2))
		}
		defer release()
		recoveryTarget := target
		if scope == "global" {
			recoveryTarget = ""
		}
		if _, guardErr = s.RecoverFilesystemMutations(lockedCtx, recoveryTarget); guardErr != nil {
			return signalExitCode(ctx, writeFailure(inv, stdout, stderr, guardErr, nil, 1))
		}
		ctx = lockedCtx
	}
	if err = app.Dispatch(ctx); err != nil {
		var partial *PartialResultError
		if errors.As(err, &partial) {
			code := partial.ExitCode
			if code == 0 {
				code = 1
			}
			return signalExitCode(ctx, writeFailure(inv, stdout, stderr, partial.Err, partial.Partial, code))
		}
		return signalExitCode(ctx, writeFailure(inv, stdout, stderr, err, nil, 1))
	}
	return signalExitCode(ctx, app.ExitCode)
}

func shouldReexecPrivilege(inv Invocation, alreadyRoot bool) bool {
	return inv.Spec.EffectivePrivilege(inv.Values) != "none" && !alreadyRoot && !inv.Globals.DryRun
}

func privilegeReexecArgs(inv Invocation, args []string) []string {
	out := append([]string(nil), args...)
	// Freeze the invoking user's config identity before a sudo transition can
	// change HOME. Android defaults are likewise made explicit for parity.
	if inv.Globals.ConfigPath == "" {
		out = append([]string{"--config", config.DefaultConfigPath(config.DetectRuntime())}, out...)
	}
	return out
}

func writeFailure(inv Invocation, stdout, stderr io.Writer, err error, partial any, code int) int {
	if inv.Globals.JSON {
		if e := emitJSONEnvelope(stdout, inv.Spec.Command, false, partial, err, partial != nil); e != nil {
			_, _ = fmt.Fprintln(stderr, "chrootctl:", redaction.String(e.Error()))
			return 1
		}
		return code
	}
	if partial != nil {
		_ = writeHuman(stdout, "Partial result", partial)
	}
	_, _ = fmt.Fprintln(stderr, "chrootctl:", redaction.String(err.Error()))
	return code
}

func signalExitCode(ctx context.Context, fallback int) int {
	cause := context.Cause(ctx)
	var signalErr SignalError
	if errors.As(cause, &signalErr) {
		switch signalErr.Signal {
		case syscall.SIGINT:
			return 130
		case syscall.SIGTERM:
			return 143
		}
		return 128 + int(signalErr.Signal)
	}
	return fallback
}

func bestCommand(args []string) string {
	if spec, ok := HelpSpecForArgs(args); ok {
		return spec.Command
	}
	return ""
}

type App struct {
	Services *services.Container
	Inv      Invocation
	Stdin    io.Reader
	Stdout   io.Writer
	Stderr   io.Writer
	ExitCode int
}

func (a *App) emit(title string, value any) error {
	if a.Inv.Globals.JSON {
		return emitJSONEnvelope(a.Stdout, a.Inv.Spec.Command, a.ExitCode == 0, value, nil, false)
	}
	return writeHuman(a.Stdout, title, value)
}

func (a *App) progress(value any) error {
	if a.Inv.Globals.JSON {
		return nil
	}
	var detail map[string]any
	if m, ok := value.(map[string]any); ok {
		detail = m
	} else {
		b, err := json.Marshal(value)
		if err != nil {
			return err
		}
		_ = json.Unmarshal(b, &detail)
	}
	if detail != nil {
		message := strings.TrimSpace(fmt.Sprint(detail["message"]))
		if message == "" || message == "<nil>" {
			message = strings.TrimSpace(fmt.Sprint(detail["phase"]))
		}
		if message != "" && message != "<nil>" {
			if percent, ok := cliProgressPercent(detail["percent"]); ok {
				_, err := fmt.Fprintf(a.Stderr, "[%3d%%] %s\n", percent, message)
				return err
			}
			_, err := fmt.Fprintf(a.Stderr, "%s\n", message)
			return err
		}
	}
	b, err := json.Marshal(value)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(a.Stderr, "%s\n", b)
	return err
}

func cliProgressPercent(value any) (int, bool) {
	var n int
	switch v := value.(type) {
	case int:
		n = v
	case int32:
		n = int(v)
	case int64:
		n = int(v)
	case float32:
		n = int(v)
	case float64:
		n = int(v)
	default:
		return 0, false
	}
	if n < 0 {
		n = 0
	}
	if n > 100 {
		n = 100
	}
	return n, true
}

func RootHelp() string {
	var b strings.Builder
	b.WriteString("usage: chrootctl [global options] COMMAND [arguments] [global options]\n\n")
	b.WriteString("Global options may appear before or after the command. Command-local options win name collisions.\n\n")
	b.WriteString("global options:\n")
	for _, a := range GlobalArguments {
		label := strings.Join(a.Options, ", ")
		if a.Action == "_StoreAction" {
			label += " VALUE"
		}
		fmt.Fprintf(&b, "  %-28s %s\n", label, a.Help)
	}
	b.WriteString("\ncommands:\n")
	groups := commandGroups()
	for _, name := range orderedGroups(groups) {
		entries := groups[name]
		if name == "__complete" || name == "app" {
			continue
		}
		if len(entries) == 1 && entries[0].Command == name {
			if !entries[0].Hidden {
				fmt.Fprintf(&b, "  %-28s %s\n", name, entries[0].Description)
			}
			continue
		}
		parts := []string{}
		for _, spec := range entries {
			if spec.Hidden || spec.Command == name {
				continue
			}
			parts = append(parts, strings.TrimPrefix(spec.Command, name+" "))
		}
		rootDescription := ""
		for _, spec := range entries {
			if spec.Command == name {
				rootDescription = spec.Description
				break
			}
		}
		if len(parts) > 0 {
			fmt.Fprintf(&b, "  %-28s %s", name, strings.Join(parts, ", "))
			if rootDescription != "" {
				fmt.Fprintf(&b, " — %s", rootDescription)
			}
			b.WriteString("\n")
		}
	}
	b.WriteString("\nUse `chrootctl COMMAND --help` for command-specific help.\n")
	b.WriteString("\nExamples:\n  chrootctl status --name work\n  chrootctl --json doctor --name work\n  chrootctl chroots list\n  chrootctl version\n")
	return b.String()
}

func commandGroups() map[string][]CommandSpec {
	groups := map[string][]CommandSpec{}
	for _, spec := range CommandSpecs {
		if len(spec.Path) > 0 {
			groups[spec.Path[0]] = append(groups[spec.Path[0]], spec)
		}
	}
	return groups
}

func orderedGroups(groups map[string][]CommandSpec) []string {
	preferred := []string{"version", "status", "doctor", "start", "restart", "exec", "install", "upgrade", "mount", "unmount", "fix-tty", "logs", "run", "enable", "disable", "journal", "chroots", "transfer", "events", "users", "tools", "addons", "clipboard", "support-bundle", "completion", "wrapper", "magisk", "app", "__complete"}
	seen := map[string]bool{}
	out := []string{}
	for _, name := range preferred {
		if _, ok := groups[name]; ok {
			out = append(out, name)
			seen[name] = true
		}
	}
	for name := range groups {
		if !seen[name] {
			out = append(out, name)
		}
	}
	return out
}

func Help(s CommandSpec) string {
	var b strings.Builder
	fmt.Fprintf(&b, "usage: chrootctl %s", s.Command)
	for _, a := range s.Arguments {
		if a.Help == "<SUPPRESS>" {
			continue
		}
		var token string
		if len(a.Options) > 0 {
			token = strings.Join(a.Options, "/")
			if a.Action == "_StoreAction" || a.Action == "_AppendAction" {
				token += " VALUE"
			}
			if !a.Required {
				token = "[" + token + "]"
			}
		} else {
			token = a.Dest
			switch fmt.Sprint(a.NArgs) {
			case "?":
				token = "[" + token + "]"
			case "*":
				token = "[" + token + " ...]"
			case "+", "...":
				token += " ..."
			default:
				token = "<" + token + ">"
			}
		}
		fmt.Fprintf(&b, " %s", token)
	}
	b.WriteString(" [global options]\n")
	if s.Description != "" {
		b.WriteString("\n" + s.Description + "\n")
	}
	if s.Group {
		children := []CommandSpec{}
		for _, candidate := range CommandSpecs {
			if candidate.Hidden || len(candidate.Path) != len(s.Path)+1 {
				continue
			}
			if strings.HasPrefix(candidate.Command, s.Command+" ") {
				children = append(children, candidate)
			}
		}
		if len(children) > 0 {
			b.WriteString("\nsubcommands:\n")
			for _, child := range children {
				fmt.Fprintf(&b, "  %-28s %s\n", child.Path[len(child.Path)-1], child.Description)
			}
		}
	}
	if len(s.Arguments) > 0 {
		b.WriteString("\narguments:\n")
	}
	for _, a := range s.Arguments {
		if a.Help == "<SUPPRESS>" {
			continue
		}
		label := a.Dest
		if len(a.Options) > 0 {
			label = strings.Join(a.Options, ", ")
		}
		meta := []string{}
		if a.Required {
			meta = append(meta, "required")
		}
		if a.Action == "_AppendAction" {
			meta = append(meta, "repeatable")
		}
		text := a.Help
		if len(meta) > 0 {
			text += " (" + strings.Join(meta, ", ") + ")"
		}
		fmt.Fprintf(&b, "  %-28s %s\n", label, text)
	}
	if len(s.ExclusiveGroups) > 0 {
		b.WriteString("\nconstraints:\n")
		for _, group := range s.ExclusiveGroups {
			labels := []string{}
			for _, key := range group {
				labels = append(labels, optionLabel(s, key))
			}
			fmt.Fprintf(&b, "  mutually exclusive: %s\n", strings.Join(labels, ", "))
		}
	}
	if s.Epilog != "" {
		b.WriteString("\n" + s.Epilog + "\n")
	}
	return b.String()
}
