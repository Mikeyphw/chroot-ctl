package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"chrootctl/internal/bridge"
	"chrootctl/internal/services"
	"chrootctl/internal/skybindfeature"
	"chrootctl/internal/skybindr1"
	"chrootctl/internal/standalonewebui"

	"chrootctl/internal/cli"
)

func main() { os.Exit(runWithIO(os.Args[1:])) }

func runWithIO(args []string) int {
	// API-03 is opt-in and root-only. Do not route through the old R1
	// read socket or chrootctl's own rclone/mount mutation dispatch.
	if len(args) > 0 && args[0] == "skybind-feature" {
		if os.Geteuid() != 0 {
			fmt.Fprintln(os.Stderr, "chrootctl skybind-feature: root required")
			return 2
		}
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		defer cancel()
		payload, err := skybindfeature.Call(ctx, args[1:], os.Stdin, skybindfeature.RunInstalled)
		if err != nil {
			if err == skybindfeature.ErrDenied && len(payload) > 0 {
				_, _ = os.Stdout.Write(payload)
			}
			fmt.Fprintln(os.Stderr, "chrootctl skybind-feature: unavailable or denied")
			return 2
		}
		_, _ = os.Stdout.Write(payload)
		return 0
	}
	// An explicit read-only integration command; no native-rclone fallback is
	// changed and no Skybind socket is accessed by default CLI operations.
	if len(args) > 0 && args[0] == "skybind-read" {
		if os.Geteuid() != 0 {
			fmt.Fprintln(os.Stderr, "chrootctl skybind-read: root module process required")
			return 2
		}
		flags := flag.NewFlagSet("skybind-read", flag.ContinueOnError)
		flags.SetOutput(os.Stderr)
		op := flags.String("operation", "", "whitelisted R1 metadata operation")
		remote := flags.String("remote", "", "operator-approved Skybind remote")
		path := flags.String("path", "", "relative path inside grant scope")
		if flags.Parse(args[1:]) != nil || len(flags.Args()) != 0 {
			return 2
		}
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		defer cancel()
		payload, err := skybindr1.Read(ctx, *op, *remote, *path)
		if err != nil {
			fmt.Fprintln(os.Stderr, "chrootctl skybind-read: read unavailable or denied")
			return 2
		}
		_, _ = os.Stdout.Write(append(payload, '\n'))
		return 0
	}
	if len(args) >= 2 && args[0] == "webui" && (args[1] == "serve" || args[1] == "start") {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		svc, err := services.New("", false, false)
		if err != nil {
			fmt.Fprintln(os.Stderr, "chrootctl webui:", err)
			return 1
		}
		defer svc.Close()
		dispatcher, err := bridge.NewServicesDispatcher(svc)
		if err != nil {
			fmt.Fprintln(os.Stderr, "chrootctl webui:", err)
			return 1
		}
		moduleDir := os.Getenv("CHROOTCTL_MODULE_DIR")
		if moduleDir == "" {
			moduleDir = "/data/adb/modules/chrootctl"
		}
		staticDir := filepath.Join(moduleDir, "webroot")
		srv, err := standalonewebui.New(standalonewebui.Config{
			IdleTimeout: 10 * time.Minute,
			SessionTTL:  30 * time.Minute,
			Dispatcher:  dispatcher,
			StaticDir:   staticDir,
			Logf: func(format string, values ...any) {
				fmt.Fprintf(os.Stderr, "chrootctl webui: "+format+"\n", values...)
			},
		})
		if err != nil {
			fmt.Fprintln(os.Stderr, "chrootctl webui:", err)
			return 1
		}
		info, err := srv.Start(ctx)
		if err != nil {
			fmt.Fprintln(os.Stderr, "chrootctl webui:", err)
			return 1
		}
		openBrowser := false
		jsonOut := false
		for _, arg := range args[2:] {
			if arg == "--open" {
				openBrowser = true
			}
			if arg == "--json" {
				jsonOut = true
			}
		}
		if jsonOut {
			_ = json.NewEncoder(os.Stdout).Encode(info)
		} else {
			fmt.Fprintln(os.Stdout, info.BootstrapURL)
		}
		if openBrowser || args[1] == "start" {
			cmd := exec.Command("/system/bin/am", "start", "-a", "android.intent.action.VIEW", "-d", info.BootstrapURL)
			if out, e := cmd.CombinedOutput(); e != nil {
				fmt.Fprintf(os.Stderr, "chrootctl webui: open browser: %v: %s\n", e, out)
			}
		}
		signals := make(chan os.Signal, 1)
		signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
		defer signal.Stop(signals)
		select {
		case <-signals:
			return 0
		case <-ctx.Done():
			return 0
		case <-srv.Done():
			return 0
		}
	}

	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
	defer signal.Stop(signals)
	go func() {
		select {
		case sig := <-signals:
			if value, ok := sig.(syscall.Signal); ok {
				cancel(cli.NewSignalError(value))
			} else {
				cancel(context.Canceled)
			}
		case <-ctx.Done():
		}
	}()
	return cli.Run(ctx, args, os.Stdin, os.Stdout, os.Stderr)
}

// run is retained for focused tests and delegates to the same signal-aware path.
func run(args []string) int { return runWithIO(args) }
