package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"chrootctl/internal/cli"
)

func main() { os.Exit(runWithIO(os.Args[1:])) }

func runWithIO(args []string) int {
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
