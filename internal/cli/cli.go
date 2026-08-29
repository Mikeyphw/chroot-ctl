package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"chrootctl/internal/bridge"
	"chrootctl/internal/completion"
	"chrootctl/internal/services"
	sys "chrootctl/internal/system"
)

var machineReadable = map[string]bool{"status": true, "doctor": true, "chroots": true, "users": true, "tools": true, "addons": true}

func Run(ctx context.Context, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	inv, err := Parse(args)
	if err != nil {
		fmt.Fprintln(stderr, "chrootctl:", err)
		fmt.Fprint(stderr, RootHelp())
		return 2
	}
	if inv.Help && inv.Spec.Command == "" {
		fmt.Fprint(stdout, RootHelp())
		return 0
	}
	if inv.Spec.Command == "completion zsh" {
		fmt.Fprint(stdout, completion.GenerateZsh())
		return 0
	}
	if inv.Help {
		fmt.Fprint(stdout, Help(inv.Spec))
		return 0
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
		return bridge.RunApp(ctx, bargs, stdin, stdout, stderr)
	}
	if inv.Globals.JSON && !machineReadable[firstWord(inv.Spec.Command)] {
		fmt.Fprintf(stderr, "chrootctl: --json is not supported for command: %s\n", firstWord(inv.Spec.Command))
		return 1
	}
	if requiresRoot(inv.Spec.Command) && !sys.IsRoot() {
		if inv.Globals.NoSudo {
			fmt.Fprintln(stderr, "chrootctl: permission error: root privileges required; rerun without --no-sudo to auto-escalate")
			return 2
		}
		argv, e := sys.ReexecArgv()
		if e != nil {
			fmt.Fprintln(stderr, "chrootctl:", e)
			return 1
		}
		runner := sys.Runner{DryRun: inv.Globals.DryRun}
		code, e := runner.ReexecWithSudo(ctx, argv)
		if e != nil {
			fmt.Fprintln(stderr, "chrootctl:", e)
			return 1
		}
		return code
	}
	s, err := services.New(inv.Globals.ConfigPath, inv.Globals.DryRun, inv.Globals.Verbose)
	if err != nil {
		fmt.Fprintln(stderr, "chrootctl:", err)
		return 1
	}
	defer s.Close()
	app := App{Services: s, Inv: inv, Stdin: stdin, Stdout: stdout, Stderr: stderr}
	if err = app.Dispatch(ctx); err != nil {
		fmt.Fprintln(stderr, "chrootctl:", err)
		return 1
	}
	return app.ExitCode
}

type App struct {
	Services *services.Container
	Inv      Invocation
	Stdin    io.Reader
	Stdout   io.Writer
	Stderr   io.Writer
	ExitCode int
}

func firstWord(s string) string {
	if i := strings.IndexByte(s, ' '); i >= 0 {
		return s[:i]
	}
	return s
}

func requiresRoot(command string) bool {
	switch command {
	case "mount", "unmount", "fix-tty", "start", "restart", "exec", "run", "enable", "disable", "install", "upgrade":
		return true
	case "chroots remove", "chroots export", "chroots import", "transfer export", "transfer import", "tools apply", "addons apply":
		return true
	}
	return command == "users" || strings.HasPrefix(command, "users ")
}

func (a *App) emit(title string, value any) error {
	if s, ok := value.(string); ok {
		_, e := fmt.Fprint(a.Stdout, s)
		if !strings.HasSuffix(s, "\n") {
			fmt.Fprintln(a.Stdout)
		}
		return e
	}
	b, e := json.MarshalIndent(value, "", "  ")
	if e != nil {
		return e
	}
	if !a.Inv.Globals.JSON && title != "" {
		fmt.Fprintln(a.Stdout, title)
	}
	_, e = a.Stdout.Write(append(b, '\n'))
	return e
}

func (a *App) progress(value any) error {
	if a.Inv.Globals.JSON {
		return nil
	}
	b, _ := json.Marshal(value)
	_, e := fmt.Fprintf(a.Stderr, "%s\n", b)
	return e
}

func RootHelp() string {
	return "usage: chrootctl [--config PATH] [--dry-run] [--verbose] [--json] [--no-sudo] [--name NAME] [--non-interactive] COMMAND\n\nUse `chrootctl COMMAND --help` for command help.\n"
}
func Help(s CommandSpec) string {
	var b strings.Builder
	fmt.Fprintf(&b, "usage: chrootctl %s", s.Command)
	for _, a := range s.Arguments {
		if len(a.Options) > 0 {
			fmt.Fprintf(&b, " [%s]", strings.Join(a.Options, "/"))
		} else {
			fmt.Fprintf(&b, " <%s>", a.Dest)
		}
	}
	b.WriteString("\n")
	if s.Description != "" {
		b.WriteString("\n" + s.Description + "\n")
	}
	if len(s.Arguments) > 0 {
		b.WriteString("\narguments:\n")
	}
	for _, a := range s.Arguments {
		label := a.Dest
		if len(a.Options) > 0 {
			label = strings.Join(a.Options, ", ")
		}
		fmt.Fprintf(&b, "  %-28s %s\n", label, a.Help)
	}
	if s.Epilog != "" {
		b.WriteString("\n" + s.Epilog + "\n")
	}
	return b.String()
}
