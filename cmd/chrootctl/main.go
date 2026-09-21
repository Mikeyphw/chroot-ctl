package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"chrootctl/internal/bridge"
	"chrootctl/internal/services"
	"chrootctl/internal/standalonewebui"

	"chrootctl/internal/cli"
)

func main() { os.Exit(runWithIO(os.Args[1:])) }

func runWithIO(args []string) int {
	if len(args) >= 2 && args[0] == "webui" && args[1] == "serve" {
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
		srv, err := standalonewebui.New(standalonewebui.Config{IdleTimeout: 10 * time.Minute, SessionTTL: 30 * time.Minute, Dispatcher: dispatcher})
		if err != nil {
			fmt.Fprintln(os.Stderr, "chrootctl webui:", err)
			return 1
		}
		info, err := srv.Start(ctx)
		if err != nil {
			fmt.Fprintln(os.Stderr, "chrootctl webui:", err)
			return 1
		}
		if len(args) > 2 && args[2] == "--json" {
			_ = json.NewEncoder(os.Stdout).Encode(info)
		} else {
			fmt.Fprintln(os.Stdout, info.BootstrapURL)
		}
		signals := make(chan os.Signal, 1)
		signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
		defer signal.Stop(signals)
		select {
		case <-signals:
			return 0
		case <-ctx.Done():
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
